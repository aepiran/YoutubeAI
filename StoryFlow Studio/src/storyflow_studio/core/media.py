"""Shared media metadata helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .process import WINDOWS_NO_WINDOW


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""


def probe_audio_duration(path: Path, timeout_seconds: int = 10) -> float | None:
    """Return audio duration through ffprobe when it is available."""

    executable = shutil.which("ffprobe")
    if not executable or not path.is_file():
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
            creationflags=WINDOWS_NO_WINDOW,
        )
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def probe_media_info(path: Path, timeout_seconds: int = 15) -> MediaInfo | None:
    """Return duration and first-video-stream metadata through ffprobe."""

    executable = shutil.which("ffprobe")
    if not executable or not path.is_file():
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration:stream=codec_name,width,height,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
            creationflags=WINDOWS_NO_WINDOW,
        )
        payload = json.loads(result.stdout)
        format_data = payload.get("format", {})
        streams = payload.get("streams", [])
        stream = streams[0] if isinstance(streams, list) and streams else {}
        duration = float(format_data.get("duration") or 0)
        if duration <= 0:
            return None
        return MediaInfo(
            duration=duration,
            width=max(0, int(stream.get("width") or 0)),
            height=max(0, int(stream.get("height") or 0)),
            fps=_parse_frame_rate(stream.get("avg_frame_rate")),
            codec=str(stream.get("codec_name") or ""),
        )
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return None


def _parse_frame_rate(value: object) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        numerator, separator, denominator = raw.partition("/")
        rate = (
            float(numerator) / float(denominator)
            if separator and float(denominator) != 0
            else float(numerator)
        )
        return round(rate, 6) if rate > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
