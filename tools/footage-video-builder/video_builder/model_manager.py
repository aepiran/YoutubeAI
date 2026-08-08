"""Inspect and download the CLIP model cache without loading model weights."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig


REQUIRED_MODEL_FILES = (
    "config.json",
    "preprocessor_config.json",
)
CLIP_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
TOKENIZER_FILE_GROUPS = (
    ("tokenizer.json", "tokenizer.model", "spiece.model"),
    ("vocab.json", "tokenizer.json", "tokenizer.model", "spiece.model"),
)
DOWNLOAD_PATTERNS = (
    *REQUIRED_MODEL_FILES,
    "merges.txt",
    "vocab.json",
    "tokenizer.model",
    "spiece.model",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "processor_config.json",
    "model.safetensors",
)


@dataclass(frozen=True)
class ModelCacheStatus:
    ready: bool
    cache_dir: Path
    found_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    weight_file: str | None

    @property
    def summary(self) -> str:
        if self.ready:
            return f"Model thị giác đã sẵn sàng ({self.weight_file})."
        return "Cache model thị giác chưa hoàn chỉnh; còn thiếu " + ", ".join(
            self.missing_files
        )


def _cached_file(config: PipelineConfig, filename: str) -> str | None:
    try:
        from huggingface_hub import try_to_load_from_cache

        result = try_to_load_from_cache(
            config.clip_model,
            filename,
            cache_dir=str(config.clip_cache_dir),
        )
        return result if isinstance(result, str) and Path(result).is_file() else None
    except (ImportError, OSError, ValueError):
        return None


def check_clip_cache(config: PipelineConfig) -> ModelCacheStatus:
    found = []
    missing = []
    for filename in REQUIRED_MODEL_FILES:
        if _cached_file(config, filename):
            found.append(filename)
        else:
            missing.append(filename)
    tokenizer_file = next(
        (
            filename
            for group in TOKENIZER_FILE_GROUPS
            for filename in group
            if _cached_file(config, filename)
        ),
        None,
    )
    if tokenizer_file:
        found.append(tokenizer_file)
    else:
        missing.append("tokenizer.json|tokenizer.model|spiece.model|vocab.json")
    weight_file = next(
        (
            filename
            for filename in CLIP_WEIGHT_FILES
            if _cached_file(config, filename)
        ),
        None,
    )
    if weight_file:
        found.append(weight_file)
    else:
        missing.append("model.safetensors|pytorch_model.bin")
    return ModelCacheStatus(
        ready=not missing,
        cache_dir=config.clip_cache_dir,
        found_files=tuple(found),
        missing_files=tuple(missing),
        weight_file=weight_file,
    )


def download_clip_cache(config: PipelineConfig) -> ModelCacheStatus:
    from huggingface_hub import snapshot_download

    config.clip_cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=config.clip_model,
        cache_dir=str(config.clip_cache_dir),
        allow_patterns=list(DOWNLOAD_PATTERNS),
    )
    status = check_clip_cache(config)
    if not status.ready:
        raise RuntimeError(status.summary)
    return status
