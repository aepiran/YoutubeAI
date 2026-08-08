"""Stage 4: detect source shots and create candidate footage windows."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from .config import PipelineConfig
from .models import Candidate

try:
    from scenedetect import AdaptiveDetector, detect as detect_video_scenes
except ImportError:
    AdaptiveDetector = None
    detect_video_scenes = None


def resize_gray(frame, width: int = 96, height: int = 54) -> np.ndarray:
    image = Image.fromarray(frame).convert("L").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    return np.asarray(image, dtype=np.float32) / 255.0


def gray_histogram(gray: np.ndarray) -> np.ndarray:
    histogram, _ = np.histogram(gray, bins=16, range=(0.0, 1.0))
    histogram = histogram.astype(np.float32)
    return histogram / max(float(histogram.sum()), 1.0)


def detect_scenes(config: PipelineConfig, path: Path, clip):
    boundaries = [0.0]
    previous_gray = None
    previous_histogram = None
    last_cut = 0.0
    for time_value, frame in clip.iter_frames(
        fps=config.scene_scan_fps, with_times=True, dtype="uint8"
    ):
        gray = resize_gray(frame)
        histogram = gray_histogram(gray)
        if previous_gray is not None:
            pixel_difference = float(np.mean(np.abs(gray - previous_gray)))
            histogram_difference = float(
                0.5 * np.sum(np.abs(histogram - previous_histogram))
            )
            enough_gap = time_value - last_cut >= config.scene_min_seconds
            if (
                enough_gap
                and pixel_difference >= config.scene_pixel_threshold
                and histogram_difference >= config.scene_histogram_threshold
            ):
                boundaries.append(float(time_value))
                last_cut = float(time_value)
        previous_gray = gray
        previous_histogram = histogram
    duration = float(clip.duration)
    if duration - boundaries[-1] < config.scene_min_seconds and len(boundaries) > 1:
        boundaries.pop()
    boundaries.append(duration)
    ranges = [
        (boundaries[index], boundaries[index + 1])
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] - boundaries[index]
        >= config.scene_min_seconds
    ]
    if ranges:
        return ranges

    # Defensive fallback for unusual videos where sampled decoding produced no
    # usable range. Normal analysis intentionally uses scene_scan_fps above so
    # a 30 fps source is not decoded frame-by-frame.
    if detect_video_scenes is not None and AdaptiveDetector is not None:
        detector = AdaptiveDetector(
            adaptive_threshold=config.scene_adaptive_threshold,
            min_scene_len=config.scene_min_seconds,
            min_content_val=config.scene_min_content_value,
        )
        scene_list = detect_video_scenes(
            str(path),
            detector,
            show_progress=False,
            start_in_scene=True,
            backend="opencv",
        )
        return [
            (float(start.seconds), float(end.seconds))
            for start, end in scene_list
            if end.seconds - start.seconds >= config.scene_min_seconds
        ]
    return []


def make_candidates(
    config: PipelineConfig,
    path: Path,
    scenes,
    source_duration: float,
    first_id: int = 0,
) -> list[Candidate]:
    candidates = []
    candidate_id = first_id
    for scene_index, (scene_start, scene_end) in enumerate(scenes):
        scene_duration = scene_end - scene_start
        if scene_duration < config.candidate_min_seconds:
            continue
        if scene_duration <= config.candidate_max_seconds:
            windows = [(scene_start, scene_end)]
        else:
            # Chia shot dài thành các vùng chính không chồng lấn. Nhiều Cut
            # liên tiếp có thể dùng cùng file theo chiều tiến mà không lặp
            # khung hình, ví dụ 0-4s rồi 4.5-9.5s.
            window_count = max(
                1,
                int(math.ceil(scene_duration / config.candidate_max_seconds)),
            )
            while (
                window_count > 1
                and scene_duration / window_count
                < config.candidate_min_seconds
            ):
                window_count -= 1
            window_duration = min(
                config.candidate_max_seconds,
                scene_duration / window_count,
            )
            windows = []
            for window_index in range(window_count):
                start = scene_start + window_index * window_duration
                end = min(scene_end, start + window_duration)
                if end - start >= config.candidate_min_seconds:
                    windows.append((start, end))

        for start, end in windows:
            duration = end - start
            if duration < config.candidate_min_seconds:
                continue
            candidates.append(
                Candidate(
                    candidate_id=candidate_id,
                    path=path,
                    scene_index=scene_index,
                    start=float(start),
                    end=float(end),
                    source_duration=source_duration,
                )
            )
            candidate_id += 1
    return candidates


def candidate_frame_times(
    config: PipelineConfig, candidate: Candidate
) -> np.ndarray:
    count = max(3, int(math.ceil(candidate.duration * config.clip_frame_fps)))
    margin = min(0.08, candidate.duration / 20)
    return np.linspace(candidate.start + margin, candidate.end - margin, count)
