"""Optional scene and vision-language adapters for Video Builder."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ...core.process import WINDOWS_NO_WINDOW


class VisualAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SceneRange:
    index: int
    start: float
    end: float


class SceneDetector(Protocol):
    def detect(
        self,
        path: Path,
        duration: float,
        threshold: float,
        minimum: float,
    ) -> tuple[SceneRange, ...]: ...


class Cancellation(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class SemanticScorer(Protocol):
    model_name: str

    def score(self, text: str, path: Path, timestamp: float) -> float: ...


class FFmpegSceneDetector:
    """Detect scene boundaries with FFmpeg and fall back to one safe range."""

    def __init__(self, scan_width: int = 426) -> None:
        self.scan_width = max(0, int(scan_width))

    def detect(
        self,
        path: Path,
        duration: float,
        threshold: float,
        minimum: float,
        *,
        cancellation: Cancellation | None = None,
    ) -> tuple[SceneRange, ...]:
        fallback = (SceneRange(0, 0.0, max(0.1, duration)),)
        executable = shutil.which("ffmpeg")
        if not executable or not path.is_file() or duration <= 0:
            return fallback
        filter_value = _scene_filter(threshold, self.scan_width)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-i",
                    str(path),
                    "-vf",
                    filter_value,
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=WINDOWS_NO_WINDOW,
            )
            deadline = time.monotonic() + max(
                20, min(300, int(math.ceil(duration * 2.0)))
            )
            while True:
                try:
                    _stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancellation is not None and cancellation.cancelled:
                        _terminate_process(process)
                        cancellation.raise_if_cancelled()
                    if time.monotonic() >= deadline:
                        _terminate_process(process)
                        return fallback
        except (OSError, subprocess.SubprocessError):
            return fallback
        finally:
            if process is not None and process.poll() is None:
                process.kill()
        boundaries = [0.0]
        for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr):
            value = float(match.group(1))
            if value - boundaries[-1] >= minimum and duration - value >= minimum:
                boundaries.append(value)
        boundaries.append(duration)
        scenes = tuple(
            SceneRange(index, round(start, 6), round(end, 6))
            for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]))
            if end - start >= minimum
        )
        return scenes or fallback


def _scene_filter(threshold: float, scan_width: int) -> str:
    scene_select = f"select='gt(scene,{threshold:.4f})',showinfo"
    if scan_width <= 0:
        return scene_select
    return (
        f"scale=w='min({scan_width},iw)':h=-2:flags=fast_bilinear,"
        f"{scene_select}"
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


class HuggingFaceSemanticScorer:
    """CLIP/SigLIP adapter loaded only when explicitly selected in Settings."""

    def __init__(
        self, model_name: str, cache_dir: Path, *, local_files_only: bool = True
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        try:
            import torch
            from transformers import AutoModel, AutoProcessor
        except ImportError as exc:
            raise VisualAnalysisError(
                "Visual Model cần optional runtime: torch, transformers và Pillow. "
                "Hãy cài runtime hoặc chọn Technical Only trong Settings."
            ) from exc
        try:
            self._torch = torch
            self._processor = AutoProcessor.from_pretrained(
                model_name,
                cache_dir=str(cache_dir),
                local_files_only=local_files_only,
            )
            self._model = AutoModel.from_pretrained(
                model_name,
                cache_dir=str(cache_dir),
                local_files_only=local_files_only,
            )
            self._text_max_length = self._resolve_text_max_length(
                self._model, self._processor
            )
            self._model.eval()
        except Exception as exc:
            if local_files_only:
                raise VisualAnalysisError(
                    "Visual Model chưa có trong local cache.\n"
                    f"Model: {model_name}\n"
                    "Cho phép StoryFlow tải model từ Hugging Face để tiếp tục."
                ) from exc
            raise VisualAnalysisError(
                f"Không tải được Visual Model {model_name} từ Hugging Face. "
                f"Kiểm tra kết nối Internet rồi thử lại.\n\nTechnical details: {exc}"
            ) from exc

    @staticmethod
    def _resolve_text_max_length(model: object, processor: object) -> int:
        """Use the model's actual positional limit, ignoring tokenizer sentinels."""
        config = getattr(model, "config", None)
        text_config = getattr(config, "text_config", None)
        tokenizer = getattr(processor, "tokenizer", None)
        candidates = (
            getattr(text_config, "max_position_embeddings", None),
            getattr(text_config, "max_length", None),
            getattr(tokenizer, "model_max_length", None),
        )
        for value in candidates:
            try:
                limit = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if 2 <= limit <= 4096:
                return limit
        return 77

    def _prepare_inputs(self, text: str, image: object) -> object:
        return self._processor(
            text=[text or "cinematic stock footage"],
            images=[image],
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=self._text_max_length,
        )

    def score(self, text: str, path: Path, timestamp: float) -> float:
        try:
            from PIL import Image
        except ImportError as exc:
            raise VisualAnalysisError("Visual Model cần cài Pillow.") from exc
        executable = shutil.which("ffmpeg")
        if not executable:
            raise VisualAnalysisError("Không tìm thấy ffmpeg để trích frame semantic.")
        with tempfile.TemporaryDirectory(prefix="storyflow-vision-") as directory:
            frame = Path(directory) / "frame.jpg"
            try:
                subprocess.run(
                    [
                        executable,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{max(0.0, timestamp):.6f}",
                        "-i",
                        str(path),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "3",
                        "-y",
                        str(frame),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                    creationflags=WINDOWS_NO_WINDOW,
                )
                with Image.open(frame) as image:
                    inputs = self._prepare_inputs(text, image.convert("RGB"))
                with self._torch.no_grad():
                    image_features = self._model.get_image_features(
                        pixel_values=inputs["pixel_values"]
                    )
                    text_keys = {
                        key: value
                        for key, value in inputs.items()
                        if key in {"input_ids", "attention_mask"}
                    }
                    text_features = self._model.get_text_features(**text_keys)
                    image_features = image_features / image_features.norm(
                        dim=-1, keepdim=True
                    )
                    text_features = text_features / text_features.norm(
                        dim=-1, keepdim=True
                    )
                    cosine = float((image_features * text_features).sum().item())
                return round(max(0.0, min(1.0, (cosine + 1.0) / 2.0)), 6)
            except VisualAnalysisError:
                raise
            except Exception as exc:
                raise VisualAnalysisError(
                    f"Không semantic-score được {path.name}: {exc}"
                ) from exc


def build_semantic_scorer(
    model_name: str, cache_dir: Path, local_files_only: bool
) -> SemanticScorer | None:
    if model_name == "disabled":
        return None
    return HuggingFaceSemanticScorer(
        model_name, cache_dir, local_files_only=local_files_only
    )
