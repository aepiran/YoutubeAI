from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Beat:
    number: int
    code: str
    main_idea: str
    keywords: str
    desired_visual: str
    avoid: str
    section: str = ""


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


@dataclass(frozen=True)
class ScriptSection:
    index: int
    name: str
    text: str


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeechSegment:
    index: int
    beats: tuple[Beat, ...]
    text: str
    start: float
    end: float
    section_index: int = 0
    section_name: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def beat_codes(self) -> str:
        return "+".join(beat.code for beat in self.beats)


@dataclass
class Candidate:
    candidate_id: int
    path: Path
    scene_index: int
    start: float
    end: float
    source_duration: float
    brightness: float = 0.0
    black_fraction: float = 0.0
    edge_energy: float = 0.0
    motion: float = 0.0
    shake: float = 0.0
    quality_score: float = 0.0
    rejected_reason: str = ""
    feature: np.ndarray | None = None
    frame_features: np.ndarray | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start
