"""Stage 5: reject poor shots and score accepted footage with CLIP."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import numpy as np
from moviepy import VideoFileClip
from PIL import Image

from .config import PipelineConfig
from .inputs import filename_beat_code, normalize_beat_code
from .models import Candidate, SpeechSegment
from .scene_candidates import (
    candidate_frame_times,
    detect_scenes,
    make_candidates,
    resize_gray,
)

try:
    import cv2
except ImportError:
    cv2 = None


class ClipModelLoadError(RuntimeError):
    """Raised when neither the local cache nor Hugging Face can provide CLIP."""


def load_clip_model(config: PipelineConfig, device: str):
    """Load the selected vision-language model and its matching processor."""
    if "siglip2" in config.clip_model.lower():
        # Current SigLIP 2 checkpoints intentionally expose model_type=siglip
        # for compatibility with the original embedding architecture.
        from transformers import SiglipModel as VisionModel
        from transformers import SiglipProcessor as VisionProcessor
    else:
        from transformers import CLIPModel as VisionModel
        from transformers import CLIPProcessor as VisionProcessor

    config.clip_cache_dir.mkdir(parents=True, exist_ok=True)
    common_options = {
        "cache_dir": str(config.clip_cache_dir),
    }
    try:
        processor = VisionProcessor.from_pretrained(
            config.clip_model,
            local_files_only=True,
            use_fast=False,
            **common_options,
        )
        model = VisionModel.from_pretrained(
            config.clip_model,
            local_files_only=True,
            **common_options,
        )
        print(f"Đang dùng model thị giác từ Cache {config.clip_cache_dir}.")
    except OSError:
        if not config.auto_download_clip:
            raise ClipModelLoadError(
                f"Model thị giác '{config.clip_model}' chưa có trên máy "
                f"và chức năng tự động tải đang tắt. Cache: "
                f"{config.clip_cache_dir}"
            )
        print(
            "Cache model thị giác bị thiếu hoặc chưa hoàn chỉnh. "
            "Đang tải model từ Hugging Face..."
        )
        try:
            processor = VisionProcessor.from_pretrained(
                config.clip_model,
                local_files_only=False,
                use_fast=False,
                **common_options,
            )
            model = VisionModel.from_pretrained(
                config.clip_model,
                local_files_only=False,
                **common_options,
            )
        except Exception as exc:
            raise ClipModelLoadError(
                f"Không thể nạp model thị giác '{config.clip_model}'. Hãy kết "
                "nối Internet trong lần chạy đầu tiên rồi thử lại. Cache model: "
                f"{config.clip_cache_dir}. Nguyên nhân: {exc}"
            ) from exc
        print(f"Đã lưu model thị giác vào Cache {config.clip_cache_dir}.")
    model = model.to(device)
    model.eval()
    return model, processor


def phase_shift(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first_fft = np.fft.fft2(first - first.mean())
    second_fft = np.fft.fft2(second - second.mean())
    cross_power = first_fft * np.conj(second_fft)
    cross_power /= np.maximum(np.abs(cross_power), 1e-8)
    correlation = np.abs(np.fft.ifft2(cross_power))
    y, x = np.unravel_index(np.argmax(correlation), correlation.shape)
    if y > first.shape[0] // 2:
        y -= first.shape[0]
    if x > first.shape[1] // 2:
        x -= first.shape[1]
    return np.array([x / first.shape[1], y / first.shape[0]], dtype=float)


def quality_metrics_from_grays(config: PipelineConfig, grays) -> dict:
    brightness = float(np.mean([gray.mean() for gray in grays]))
    black_fraction = float(np.mean([np.mean(gray < 0.04) for gray in grays]))
    if cv2 is not None:
        edge_energy = float(
            np.mean(
                [
                    cv2.Laplacian(
                        np.uint8(np.clip(gray * 255.0, 0, 255)),
                        cv2.CV_64F,
                    ).var()
                    for gray in grays
                ]
            )
        )
    else:
        edge_energy = float(
            10000.0
            * np.mean(
                [
                    (
                        np.mean(np.abs(np.diff(gray, axis=0)))
                        + np.mean(np.abs(np.diff(gray, axis=1)))
                    )
                    / 2
                    for gray in grays
                ]
            )
        )

    if len(grays) > 1:
        motion = float(
            np.mean(
                [
                    np.mean(np.abs(second - first))
                    for first, second in zip(grays, grays[1:])
                ]
            )
        )
        if cv2 is not None:
            shifts = []
            for first, second in zip(grays, grays[1:]):
                first_u8 = np.uint8(np.clip(first * 255.0, 0, 255))
                second_u8 = np.uint8(np.clip(second * 255.0, 0, 255))
                points = cv2.goodFeaturesToTrack(
                    first_u8,
                    maxCorners=120,
                    qualityLevel=0.01,
                    minDistance=5,
                    blockSize=5,
                )
                if points is None or len(points) < 6:
                    shifts.append(phase_shift(first, second))
                    continue
                tracked, status, _ = cv2.calcOpticalFlowPyrLK(
                    first_u8,
                    second_u8,
                    points,
                    None,
                    winSize=(15, 15),
                    maxLevel=2,
                )
                valid = status.reshape(-1).astype(bool)
                if tracked is None or valid.sum() < 6:
                    shifts.append(phase_shift(first, second))
                    continue
                displacement = (
                    tracked.reshape(-1, 2)[valid] - points.reshape(-1, 2)[valid]
                )
                median_shift = np.median(displacement, axis=0)
                shifts.append(
                    np.array(
                        [
                            median_shift[0] / first.shape[1],
                            median_shift[1] / first.shape[0],
                        ],
                        dtype=float,
                    )
                )
            shifts = np.asarray(shifts)
        else:
            shifts = np.asarray(
                [
                    phase_shift(first, second)
                    for first, second in zip(grays, grays[1:])
                ]
            )
        shift_changes = np.diff(shifts, axis=0)
        shake = (
            float(np.mean(np.linalg.norm(shift_changes, axis=1)))
            if len(shift_changes)
            else 0.0
        )
    else:
        motion = 0.0
        shake = 0.0

    reasons = []
    if brightness < config.min_brightness:
        reasons.append("too_dark")
    if brightness > config.max_brightness:
        reasons.append("overexposed")
    if black_fraction > config.max_black_fraction:
        reasons.append("mostly_black")
    if edge_energy < config.min_edge_energy:
        reasons.append("blurry")
    if motion < config.min_motion:
        reasons.append("low_motion")
    if shake > config.max_shake:
        reasons.append("shaky")
    brightness_score = max(0.0, 1.0 - abs(brightness - 0.45) / 0.45)
    quality_score = (
        0.30 * brightness_score
        + 0.25 * min(1.0, edge_energy / 250.0)
        + 0.25 * min(1.0, motion / 0.08)
        + 0.20 * max(0.0, 1.0 - shake / config.max_shake)
    )
    return {
        "brightness": brightness,
        "black_fraction": black_fraction,
        "edge_energy": edge_energy,
        "motion": motion,
        "shake": shake,
        "quality_score": quality_score,
        "rejected_reason": ",".join(reasons),
    }


def quality_metrics(config: PipelineConfig, frames) -> dict:
    return quality_metrics_from_grays(
        config,
        [resize_gray(frame) for frame in frames],
    )


def clip_image_feature(
    config: PipelineConfig, model, processor, device: str, frames
) -> tuple[np.ndarray, np.ndarray]:
    import torch

    features = []
    for start in range(0, len(frames), config.clip_batch_size):
        inputs = processor(
            images=frames[start : start + config.clip_batch_size],
            return_tensors="pt",
        )
        with torch.no_grad():
            output = model.get_image_features(
                pixel_values=inputs["pixel_values"].to(device)
            )
            output = output / output.norm(dim=-1, keepdim=True)
        features.append(output.cpu().numpy())
    frame_features = np.concatenate(features, axis=0)
    mean_feature = frame_features.mean(axis=0)
    mean_feature = mean_feature / max(
        float(np.linalg.norm(mean_feature)), 1e-8
    )
    return mean_feature, frame_features


_FOOTAGE_CACHE_SCHEMA = 2
_CANDIDATE_FIELDS = (
    "scene_index",
    "start",
    "end",
    "source_duration",
    "brightness",
    "black_fraction",
    "edge_energy",
    "motion",
    "shake",
    "quality_score",
    "rejected_reason",
)
_ANALYSIS_CONFIG_FIELDS = (
    "clip_model",
    "scene_scan_fps",
    "scene_min_seconds",
    "scene_adaptive_threshold",
    "scene_min_content_value",
    "scene_histogram_threshold",
    "scene_pixel_threshold",
    "candidate_min_seconds",
    "candidate_max_seconds",
    "candidate_target_seconds",
    "candidate_step_seconds",
    "clip_frame_fps",
    "min_brightness",
    "max_brightness",
    "max_black_fraction",
    "min_edge_energy",
    "min_motion",
    "max_shake",
)


def _analysis_signature(config: PipelineConfig, path: Path) -> dict:
    stat = path.stat()
    return {
        "schema": _FOOTAGE_CACHE_SCHEMA,
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": {
            field: getattr(config, field)
            for field in _ANALYSIS_CONFIG_FIELDS
        },
        "scene_detector": (
            f"sampled-{config.scene_scan_fps:g}fps"
            if config.scene_scan_fps > 0
            else "scenedetect"
        ),
    }


def _analysis_cache_paths(
    config: PipelineConfig, path: Path
) -> tuple[Path, Path]:
    key = hashlib.sha256(
        str(path.resolve()).lower().encode("utf-8")
    ).hexdigest()
    directory = config.cache_dir / "footage_analysis"
    return directory / f"{key}.json", directory / f"{key}.npz"


def _candidate_metadata(candidate: Candidate) -> dict:
    return {
        field: getattr(candidate, field)
        for field in _CANDIDATE_FIELDS
    }


def _candidate_from_metadata(path: Path, data: dict) -> Candidate:
    return Candidate(
        candidate_id=0,
        path=path,
        scene_index=int(data["scene_index"]),
        start=float(data["start"]),
        end=float(data["end"]),
        source_duration=float(data["source_duration"]),
        brightness=float(data.get("brightness", 0.0)),
        black_fraction=float(data.get("black_fraction", 0.0)),
        edge_energy=float(data.get("edge_energy", 0.0)),
        motion=float(data.get("motion", 0.0)),
        shake=float(data.get("shake", 0.0)),
        quality_score=float(data.get("quality_score", 0.0)),
        rejected_reason=str(data.get("rejected_reason", "")),
    )


def _load_video_analysis_cache(
    config: PipelineConfig, path: Path
) -> tuple[list[Candidate], list[Candidate]] | None:
    metadata_path, arrays_path = _analysis_cache_paths(config, path)
    if not metadata_path.is_file() or not arrays_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if payload.get("signature") != _analysis_signature(config, path):
            return None
        accepted = [
            _candidate_from_metadata(path, item)
            for item in payload.get("accepted", [])
        ]
        rejected = [
            _candidate_from_metadata(path, item)
            for item in payload.get("rejected", [])
        ]
        with np.load(arrays_path, allow_pickle=False) as arrays:
            features = arrays["features"]
            frame_features = arrays["frame_features"]
            frame_offsets = arrays["frame_offsets"]
            if len(features) != len(accepted):
                return None
            if len(frame_offsets) != len(accepted) + 1:
                return None
            for index, candidate in enumerate(accepted):
                candidate.feature = np.asarray(features[index])
                candidate.frame_features = np.asarray(
                    frame_features[
                        int(frame_offsets[index]) : int(frame_offsets[index + 1])
                    ]
                )
        return accepted, rejected
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _save_video_analysis_cache(
    config: PipelineConfig,
    path: Path,
    accepted: list[Candidate],
    rejected: list[Candidate],
) -> None:
    metadata_path, arrays_path = _analysis_cache_paths(config, path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    feature_width = next(
        (
            int(candidate.feature.shape[-1])
            for candidate in accepted
            if candidate.feature is not None
        ),
        0,
    )
    features = (
        np.stack([candidate.feature for candidate in accepted]).astype(
            np.float32, copy=False
        )
        if accepted
        else np.empty((0, feature_width), dtype=np.float32)
    )
    frame_counts = [
        len(candidate.frame_features)
        if candidate.frame_features is not None
        else 0
        for candidate in accepted
    ]
    frame_offsets = np.zeros(len(frame_counts) + 1, dtype=np.int64)
    if frame_counts:
        frame_offsets[1:] = np.cumsum(frame_counts)
    frame_arrays = [
        candidate.frame_features
        for candidate in accepted
        if candidate.frame_features is not None and len(candidate.frame_features)
    ]
    frame_features = (
        np.concatenate(frame_arrays, axis=0).astype(np.float32, copy=False)
        if frame_arrays
        else np.empty((0, feature_width), dtype=np.float32)
    )
    payload = {
        "signature": _analysis_signature(config, path),
        "accepted": [_candidate_metadata(item) for item in accepted],
        "rejected": [_candidate_metadata(item) for item in rejected],
    }
    arrays_temporary = arrays_path.with_suffix(".npz.tmp")
    metadata_temporary = metadata_path.with_suffix(".json.tmp")
    try:
        with arrays_temporary.open("wb") as handle:
            np.savez(
                handle,
                features=features,
                frame_features=frame_features,
                frame_offsets=frame_offsets,
            )
        metadata_temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        arrays_temporary.replace(arrays_path)
        metadata_temporary.replace(metadata_path)
    except OSError as exc:
        print(f"Cảnh báo: không thể lưu Cache Footage {path.name}: {exc}")


def _candidate_frame_keys(
    config: PipelineConfig, candidate: Candidate
) -> tuple[float, ...]:
    fps = max(float(config.clip_frame_fps), 0.1)
    margin = min(0.08, candidate.duration / 20)
    lower = candidate.start + margin
    upper = candidate.end - margin
    keys = []
    for value in candidate_frame_times(config, candidate):
        quantized = round(float(value) * fps) / fps
        keys.append(round(min(upper, max(lower, quantized)), 6))
    return tuple(dict.fromkeys(keys))


def analyze_one_video(
    config: PipelineConfig,
    video_index: int,
    video_count: int,
    path: Path,
    model,
    processor,
    device: str,
    inference_lock: Lock,
    force_refresh: bool = False,
) -> dict:
    result = {
        "video_index": video_index,
        "video_count": video_count,
        "path": path,
        "scene_count": 0,
        "candidate_count": 0,
        "accepted": [],
        "rejected": [],
        "error": "",
        "cached": False,
    }
    cached = None if force_refresh else _load_video_analysis_cache(config, path)
    if cached is not None:
        result["accepted"], result["rejected"] = cached
        result["candidate_count"] = len(result["accepted"]) + len(
            result["rejected"]
        )
        result["scene_count"] = len(
            {
                candidate.scene_index
                for candidate in result["accepted"] + result["rejected"]
            }
        )
        result["cached"] = True
        return result
    print(
        f"Footage [{video_index}/{video_count}] bắt đầu: {path.name}",
        flush=True,
    )
    try:
        clip = VideoFileClip(str(path), audio=False)
    except Exception as exc:
        result["error"] = f"không thể decode ({exc})"
        return result
    try:
        scenes = detect_scenes(config, path, clip)
        candidates = make_candidates(
            config, path, scenes, float(clip.duration), first_id=0
        )
        result["scene_count"] = len(scenes)
        result["candidate_count"] = len(candidates)
        keys_by_candidate = [
            _candidate_frame_keys(config, candidate)
            for candidate in candidates
        ]
        all_keys = sorted(
            {
                key
                for keys in keys_by_candidate
                for key in keys
            }
        )
        frame_cache = {}
        for key in all_keys:
            frame = clip.get_frame(key)
            image = Image.fromarray(frame).convert("RGB")
            image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            frame_cache[key] = (resize_gray(frame), image)

        accepted_with_keys = []
        for candidate, frame_keys in zip(candidates, keys_by_candidate):
            grays = [frame_cache[key][0] for key in frame_keys]
            for key, value in quality_metrics_from_grays(
                config, grays
            ).items():
                setattr(candidate, key, value)
            if candidate.rejected_reason:
                result["rejected"].append(candidate)
                continue
            accepted_with_keys.append((candidate, frame_keys))

        accepted_keys = sorted(
            {
                key
                for _, frame_keys in accepted_with_keys
                for key in frame_keys
            }
        )
        if accepted_keys:
            with inference_lock:
                _, unique_features = clip_image_feature(
                    config,
                    model,
                    processor,
                    device,
                    [frame_cache[key][1] for key in accepted_keys],
                )
            feature_by_key = dict(zip(accepted_keys, unique_features))
            for candidate, frame_keys in accepted_with_keys:
                candidate.frame_features = np.stack(
                    [feature_by_key[key] for key in frame_keys],
                    axis=0,
                )
                candidate.feature = candidate.frame_features.mean(axis=0)
                candidate.feature = candidate.feature / max(
                    float(np.linalg.norm(candidate.feature)), 1e-8
                )
                result["accepted"].append(candidate)
        _save_video_analysis_cache(
            config,
            path,
            result["accepted"],
            result["rejected"],
        )
    except Exception as exc:
        result["error"] = f"phân tích thất bại ({exc})"
    finally:
        clip.close()
    return result


def analyze_footage(
    config: PipelineConfig,
    video_files: list[Path],
    force_refresh: bool = False,
):
    import torch

    worker_count = min(config.analysis_workers, len(video_files))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Đang nạp {config.clip_model} trên {device}...")
    model, processor = load_clip_model(config, device)
    accepted = []
    rejected = []
    inference_lock = Lock()
    print(
        f"Phân tích Footage: {worker_count} Worker decode/Scene, "
        "dùng chung một hàng đợi inference của model thị giác."
    )
    with ThreadPoolExecutor(
        max_workers=worker_count, thread_name_prefix="footage"
    ) as executor:
        futures = {
            executor.submit(
                analyze_one_video,
                config,
                video_index,
                len(video_files),
                path,
                model,
                processor,
                device,
                inference_lock,
                force_refresh,
            ): path
            for video_index, path in enumerate(video_files, start=1)
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            path = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                print(
                    f"[{completed_count}/{len(video_files)} complete] "
                    f"{path.name}: Worker gặp lỗi ({exc})"
                )
                continue
            if result["error"]:
                print(
                    f"[{completed_count}/{len(video_files)} complete] "
                    f"{path.name}: bị loại ({result['error']})"
                )
            else:
                cache_label = " (Cache)" if result.get("cached") else ""
                print(
                    f"[{completed_count}/{len(video_files)} complete] "
                    f"{path.name}: {result['scene_count']} Scene, "
                    f"{result['candidate_count']} Candidate, "
                    f"{len(result['accepted'])} được chấp nhận{cache_label}"
                )
            accepted.extend(result["accepted"])
            rejected.extend(result["rejected"])
    if not accepted:
        raise RuntimeError("Tất cả Footage Candidate đều bị loại")
    accepted.sort(key=lambda item: (str(item.path).lower(), item.start, item.end))
    rejected.sort(key=lambda item: (str(item.path).lower(), item.start, item.end))
    for candidate_id, candidate in enumerate(accepted):
        candidate.candidate_id = candidate_id
    print(
        f"Lọc Candidate: {len(accepted)} được chấp nhận, "
        f"{len(rejected)} bị loại."
    )
    return accepted, rejected, model, processor, device


def clip_text_features(model, processor, device: str, texts) -> np.ndarray:
    import torch

    is_siglip = "siglip" in type(model).__name__.lower()
    inputs = processor(
        text=texts,
        return_tensors="pt",
        padding="max_length" if is_siglip else True,
        truncation=True,
        max_length=64 if is_siglip else 77,
    )
    text_inputs = {
        key: value.to(device)
        for key, value in inputs.items()
        if key in {"input_ids", "attention_mask", "token_type_ids"}
    }
    with torch.no_grad():
        features = model.get_text_features(**text_inputs)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()


def filename_beat_number(path: Path) -> int | None:
    code = filename_beat_code(path)
    match = re.search(r"(\d+)", code or "")
    return int(match.group(1)) if match else None


def keyword_set(text: str) -> set[str]:
    stop = {
        "a", "an", "and", "are", "as", "at", "be", "for", "from", "in",
        "into", "is", "it", "of", "on", "or", "that", "the", "this", "to",
        "video", "with", "without",
    }
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in stop
    }


def build_score_matrix(
    config: PipelineConfig,
    segments: list[SpeechSegment],
    candidates: list[Candidate],
    model,
    processor,
    device: str,
    script_overview: dict | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Score every semantic CSV field independently and keep it auditable."""

    def candidate_frames(candidate: Candidate) -> np.ndarray:
        if candidate.frame_features is not None:
            return candidate.frame_features
        if candidate.feature is None:
            raise RuntimeError(
                f"Candidate has no CLIP feature: {candidate.path}"
            )
        return candidate.feature[None, :]

    candidate_frame_arrays = [
        candidate_frames(candidate)
        for candidate in candidates
    ]
    text_feature_cache: dict[str, np.ndarray] = {}

    def cached_text_features(texts: list[str]) -> np.ndarray:
        normalized = [text.strip() for text in texts]
        missing = list(
            dict.fromkeys(
                text
                for text in normalized
                if text and text not in text_feature_cache
            )
        )
        for start in range(0, len(missing), 256):
            batch = missing[start : start + 256]
            features = clip_text_features(
                model, processor, device, batch
            )
            for text, feature in zip(batch, features):
                text_feature_cache[text] = feature
        return np.stack(
            [text_feature_cache[text] for text in normalized],
            axis=0,
        )

    def positive_scores(
        prompts_by_segment: list[list[str]],
    ) -> np.ndarray:
        flat_prompts = []
        owners = []
        for segment_index, prompts in enumerate(prompts_by_segment):
            for prompt in prompts:
                if prompt.strip():
                    flat_prompts.append(prompt.strip())
                    owners.append(segment_index)
        result = np.zeros((len(segments), len(candidates)), dtype=float)
        counts = np.zeros(len(segments), dtype=float)
        if not flat_prompts:
            return result
        text_features = cached_text_features(flat_prompts)
        for prompt_index, segment_index in enumerate(owners):
            for candidate_index, frames in enumerate(candidate_frame_arrays):
                similarities = (
                    frames @ text_features[prompt_index]
                )
                top_count = min(2, len(similarities))
                top_values = np.partition(
                    similarities, len(similarities) - top_count
                )[-top_count:]
                result[segment_index, candidate_index] += float(
                    np.mean(top_values)
                )
            counts[segment_index] += 1.0
        for segment_index, count in enumerate(counts):
            if count:
                result[segment_index] /= count
        return result

    desired = positive_scores(
        [
            [
                f"Documentary stock footage showing {beat.desired_visual}"
                for beat in segment.beats
            ]
            for segment in segments
        ]
    )
    main_idea = positive_scores(
        [
            [
                f"Documentary visual illustrating {beat.main_idea}"
                for beat in segment.beats
            ]
            for segment in segments
        ]
    )
    keywords = positive_scores(
        [
            [
                f"Stock footage of {keyword.strip()}"
                for beat in segment.beats
                for keyword in re.split(r"[,;\n|]+", beat.keywords)
                if keyword.strip()
            ]
            for segment in segments
        ]
    )
    narration = positive_scores(
        [
            [f"Documentary footage illustrating {segment.text}"]
            for segment in segments
        ]
    )
    overview_prompt = (
        str((script_overview or {}).get("semantic_prompt", "")).strip()
    )
    overview = positive_scores(
        [[overview_prompt] for _segment in segments]
    )

    avoid_prompts_by_segment = []
    for segment in segments:
        concepts = [
            concept.strip()
            for beat in segment.beats
            for concept in re.split(r"[,;\n|]+", beat.avoid)
            if concept.strip()
        ]
        avoid_prompts_by_segment.append(
            [f"Footage containing {concept}" for concept in concepts]
        )
    all_avoid_prompts = [
        prompt
        for prompts in avoid_prompts_by_segment
        for prompt in prompts
    ]
    if all_avoid_prompts:
        cached_text_features(all_avoid_prompts)

    avoid = np.zeros((len(segments), len(candidates)), dtype=float)
    for segment_index, prompts in enumerate(avoid_prompts_by_segment):
        if not prompts:
            continue
        text_features = cached_text_features(prompts)
        for candidate_index, frames in enumerate(candidate_frame_arrays):
            frame_scores = (
                frames @ text_features.T
            )
            avoid[segment_index, candidate_index] = float(
                np.max(frame_scores)
            )

    quality = np.broadcast_to(
        np.asarray(
            [candidate.quality_score for candidate in candidates],
            dtype=float,
        )[None, :],
        (len(segments), len(candidates)),
    ).copy()
    beat_identity = np.zeros_like(quality)
    cross_beat_fallback = np.zeros_like(quality)
    fallback_eligible = np.zeros_like(quality)
    forced_low_semantic = np.zeros_like(quality)
    avoid_rejected = np.zeros_like(quality, dtype=bool)
    known_codes = {
        normalize_beat_code(beat.code)
        for segment in segments
        for beat in segment.beats
    }
    candidate_beat_codes = [
        filename_beat_code(candidate.path, known_codes)
        for candidate in candidates
    ]
    candidate_beat_numbers = [
        filename_beat_number(candidate.path)
        if candidate_beat_codes[index] is None
        else None
        for index, candidate in enumerate(candidates)
    ]
    candidate_filename_keywords = [
        keyword_set(candidate.path.stem.replace("-", " "))
        for candidate in candidates
    ]

    for segment_index, segment in enumerate(segments):
        beat_numbers = {beat.number for beat in segment.beats}
        beat_codes = {normalize_beat_code(beat.code) for beat in segment.beats}
        query_words = keyword_set(
            " ".join(beat.keywords for beat in segment.beats)
        )
        positive_reference = np.maximum(
            desired[segment_index], main_idea[segment_index]
        )
        avoid_rejected[segment_index] = (
            (avoid[segment_index] >= config.avoid_reject_threshold)
            & (
                avoid[segment_index]
                > positive_reference + config.avoid_reject_margin
            )
        )
        for candidate_index, candidate_beat in enumerate(
            candidate_beat_numbers
        ):
            candidate_code = candidate_beat_codes[candidate_index]
            if candidate_code in beat_codes or candidate_beat in beat_numbers:
                beat_identity[segment_index, candidate_index] = 1.0
            overlap = len(
                query_words
                & candidate_filename_keywords[candidate_index]
            )
            keywords[segment_index, candidate_index] += min(
                0.08, overlap * 0.02
            )

        # Keep semantically relevant candidates from other Beats available.
        # They carry a fallback penalty, but can now replace an exact source
        # that would otherwise repeat frames because its coverage is scarce.
        cross_beat_fallback[segment_index] = (
            beat_identity[segment_index] == 0
        ).astype(float)

    # Keep content suitability separate from quality, global overview and Beat
    # ownership. A polished but unrelated generic shot must not become a
    # fallback merely because every alternative is worse.
    semantic_fit = (
        0.45 * desired
        + 0.25 * main_idea
        + 0.15 * keywords
        + 0.15 * narration
    )
    for segment_index in range(len(segments)):
        valid = ~avoid_rejected[segment_index]
        matching = beat_identity[segment_index] >= 0.5
        fallback_eligible[segment_index, matching & valid] = 1.0
        cross = (~matching) & valid
        if not np.any(cross):
            continue
        best_content = float(np.max(semantic_fit[segment_index, valid]))
        semantic_threshold = max(
            config.fallback_semantic_min,
            best_content - config.fallback_semantic_margin,
        )
        suitable = cross & (
            semantic_fit[segment_index] + 1e-9 >= semantic_threshold
        )
        fallback_eligible[segment_index, suitable] = 1.0
        if not np.any(suitable):
            # Keep one emergency choice so source shortages remain renderable.
            # It receives a strong score penalty and an explicit report warning.
            cross_indexes = np.flatnonzero(cross)
            best_cross = int(
                cross_indexes[
                    np.argmax(semantic_fit[segment_index, cross_indexes])
                ]
            )
            fallback_eligible[segment_index, best_cross] = 1.0
            forced_low_semantic[segment_index, best_cross] = 1.0

    scores = (
        config.score_overview_weight * overview
        + config.score_desired_visual_weight * desired
        + config.score_main_idea_weight * main_idea
        + config.score_keywords_weight * keywords
        + config.score_narration_weight * narration
        + config.score_quality_weight * quality
        + config.score_beat_identity_weight * beat_identity
        - config.score_avoid_penalty * avoid
        - config.cross_beat_fallback_penalty * cross_beat_fallback
        - config.forced_fallback_penalty * forced_low_semantic
    )

    for segment_index in range(len(segments)):
        scores[segment_index, avoid_rejected[segment_index]] = -1e6
        if np.all(scores[segment_index] <= -1e5):
            # Preserve one auditable emergency fallback when every candidate
            # was rejected; the optimizer still receives the avoid penalty.
            scores[segment_index] = (
                config.score_overview_weight * overview[segment_index]
                + config.score_desired_visual_weight * desired[segment_index]
                + config.score_main_idea_weight * main_idea[segment_index]
                + config.score_keywords_weight * keywords[segment_index]
                + config.score_narration_weight * narration[segment_index]
                + config.score_quality_weight * quality[segment_index]
                - config.score_avoid_penalty * avoid[segment_index]
                - config.cross_beat_fallback_penalty
            )
            cross_beat_fallback[segment_index] = 1.0
            fallback_eligible[segment_index] = 0.0
            forced_index = int(np.argmax(scores[segment_index]))
            fallback_eligible[segment_index, forced_index] = 1.0
            forced_low_semantic[segment_index, forced_index] = 1.0
            scores[
                segment_index, forced_index
            ] -= config.forced_fallback_penalty

    components = {
        "overview_score": overview,
        "desired_visual_score": desired,
        "main_idea_score": main_idea,
        "keyword_score": keywords,
        "narration_score": narration,
        "avoid_score": avoid,
        "quality_score": quality,
        "beat_identity_score": beat_identity,
        "cross_beat_fallback": cross_beat_fallback,
        "semantic_fit_score": semantic_fit,
        "fallback_eligible": fallback_eligible,
        "forced_low_semantic": forced_low_semantic,
        "avoid_rejected": avoid_rejected.astype(float),
        "final_score": scores.copy(),
    }
    return scores, components
