"""Render analyzed timelines without keeping every MoviePy clip in memory."""

from __future__ import annotations

import csv
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from .capcut_export.media_exporter import export_capcut_scenes
from .audio_mix import load_configured_music_rows, mix_audio_with_music
from .config import PipelineConfig
from .subprocess_utils import hidden_subprocess_kwargs


def _concat_line(path: Path) -> str:
    value = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{value}'"


def _narration_mux_command(
    ffmpeg: str,
    concat_file: Path,
    narration: Path,
    output_file: Path,
) -> list[str]:
    """Mux the complete narration; visual duration must never trim audio."""
    return [
        ffmpeg,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-i", str(narration),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        # Deliberately do not use -shortest. If rounding makes the visual
        # stream slightly shorter, FFmpeg must still mux every audio sample.
        str(output_file),
    ]


def render_report_low_memory(
    config: PipelineConfig,
    report: dict,
    audio_clip,
) -> None:
    """Export one cut at a time, concatenate, then mux narration audio."""
    rows = report.get("timeline", [])
    if not rows:
        raise ValueError("Report không có Timeline để Render")
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.output_file.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    total_duration = max(
        float(audio_clip.duration),
        max((float(row.get("timeline_end", 0.0)) for row in rows), default=0.0),
    )
    with tempfile.TemporaryDirectory(
        prefix="footage-render-",
        dir=str(config.cache_dir),
    ) as temporary:
        root = Path(temporary)
        scenes_dir = root / "scenes"
        manifest_path = export_capcut_scenes(
            config, rows, scenes_dir
        )
        with manifest_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            scene_rows = list(csv.DictReader(handle))
        concat_file = root / "concat.txt"
        concat_file.write_text(
            "\n".join(
                _concat_line(scenes_dir / row["scene_file"])
                for row in scene_rows
            )
            + "\n",
            encoding="utf-8",
        )
        narration = root / "narration.wav"
        music_rows = load_configured_music_rows(config, total_duration)
        mixed_audio, music_clips = mix_audio_with_music(
            audio_clip, music_rows, duration=total_duration
        )
        try:
            if music_rows:
                print(
                    f"Nhạc nền DWG: {len(music_rows)} cue từ "
                    f"{config.music_cue_sheet.name}."
                )
            mixed_audio.write_audiofile(
                str(narration),
                fps=48_000,
                codec="pcm_s16le",
                logger=None,
            )
        finally:
            if mixed_audio is not audio_clip:
                mixed_audio.close()
            for clip in music_clips:
                clip.close()
        command = _narration_mux_command(
            ffmpeg,
            concat_file,
            narration,
            config.output_file,
        )
        command[-1:-1] = ["-progress", "pipe:1", "-nostats"]
        print(
            f"Đang xuất {config.output_file.name} "
            "(chế độ tiết kiệm RAM)..."
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        assert process.stdout is not None
        last_percent = -1
        output_tail = []
        for line in process.stdout:
            output_tail.append(line.rstrip())
            output_tail = output_tail[-40:]
            key, separator, value = line.strip().partition("=")
            if not separator or key not in {"out_time_us", "out_time_ms"}:
                continue
            try:
                progress_seconds = int(value) / 1_000_000
            except ValueError:
                continue
            percent = max(
                0,
                min(
                    99,
                    round(
                        100 * progress_seconds
                        / max(total_duration, 0.001)
                    ),
                ),
            )
            if percent != last_percent:
                last_percent = percent
                print(f"OUTPUT_PROGRESS: {percent}", flush=True)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(
                "FFmpeg không thể ghép Video: "
                + (
                    "\n".join(output_tail).strip()
                    or f"mã lỗi {process.returncode}"
                )
            )
        print("OUTPUT_PROGRESS: 100", flush=True)
