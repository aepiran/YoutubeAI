"""Shared media metadata helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


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
        )
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
