from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class CapCutPackage:
    root: Path
    scenes_dir: Path
    narration_file: Path
    captions_file: Path
    manifest_file: Path
    reference_video: Path | None
