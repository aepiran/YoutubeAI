"""Project metrics displayed by workflow stage cards."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...core.media import probe_audio_duration
from .service import Project


@dataclass(frozen=True, slots=True)
class ProjectMetrics:
    word_count: int = 0
    character_count: int = 0
    script_source: str = ""
    audio_duration_seconds: float | None = None
    beat_count: int = 0
    music_cue_count: int = 0
    footage_count: int = 0
    video_cut_count: int = 0
    video_warning_count: int = 0


class ProjectMetricsService:
    def __init__(
        self,
        duration_probe: Callable[[Path], float | None] = probe_audio_duration,
    ) -> None:
        self.duration_probe = duration_probe

    def snapshot(self, project: Project) -> ProjectMetrics:
        script_path = self._preferred_script(project)
        script = self._read_text(script_path)
        audio_path = project.path_for("audio_file")
        subtitle_path = project.path_for("subtitle_file")
        duration = self.duration_probe(audio_path) if audio_path.is_file() else None
        if duration is None:
            duration = self._srt_duration(subtitle_path)
        video_cut_count, video_warning_count = self._video_timeline_metrics(
            project.path_for("video_timeline_file")
        )
        return ProjectMetrics(
            word_count=len(_words(script)),
            character_count=len(script.strip()),
            script_source=script_path.name if script else "",
            audio_duration_seconds=duration,
            beat_count=self._beat_count(project.path_for("beat_file")),
            music_cue_count=self._music_cue_count(
                project.path_for("music_cue_file")
            ),
            footage_count=self._footage_count(project.path_for("footage_dir")),
            video_cut_count=video_cut_count,
            video_warning_count=video_warning_count,
        )

    @staticmethod
    def _preferred_script(project: Project) -> Path:
        tts_script = project.path_for("tts_script")
        if tts_script.is_file() and tts_script.stat().st_size > 0:
            return tts_script
        return project.path_for("raw_script")

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig") if path.is_file() else ""
        except OSError:
            return ""

    @staticmethod
    def _beat_count(path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return sum(
                    1
                    for row in csv.DictReader(handle)
                    if (row.get("ma_beat") or "").strip()
                )
        except (OSError, csv.Error):
            return 0

    @staticmethod
    def _music_cue_count(path: Path) -> int:
        if not path.is_file():
            return 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return sum(
                    1
                    for row in csv.DictReader(handle)
                    if (row.get("cue") or "").strip()
                )
        except (OSError, csv.Error):
            return 0

    @staticmethod
    def _footage_count(path: Path) -> int:
        if not path.is_dir():
            return 0
        try:
            return sum(
                1
                for item in path.iterdir()
                if item.is_file() and item.suffix.lower() == ".mp4"
            )
        except OSError:
            return 0

    @staticmethod
    def _video_timeline_metrics(path: Path) -> tuple[int, int]:
        if not path.is_file():
            return 0, 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0, 0
        if not isinstance(payload, dict):
            return 0, 0
        timeline = payload.get("timeline")
        if not isinstance(timeline, list):
            return 0, 0
        warnings = sum(
            len(item.get("warnings", []))
            for item in timeline
            if isinstance(item, dict) and isinstance(item.get("warnings", []), list)
        )
        return len(timeline), warnings

    @staticmethod
    def _srt_duration(path: Path) -> float | None:
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return None
        matches = re.findall(
            r"-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            content,
        )
        if not matches:
            return None
        hours, minutes, seconds, milliseconds = map(int, matches[-1])
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", value, flags=re.UNICODE)
