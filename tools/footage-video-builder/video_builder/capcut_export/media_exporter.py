from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from ..config import PipelineConfig
from ..subprocess_utils import hidden_subprocess_kwargs


def _remove_previous_generated_scenes(output_dir: Path) -> None:
    manifest_path = output_dir / "selected_scenes.csv"
    if not manifest_path.is_file():
        return
    with manifest_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        previous = list(csv.DictReader(handle))
    resolved_output = output_dir.resolve()
    for row in previous:
        filename = Path(str(row.get("scene_file", ""))).name
        if not filename:
            continue
        candidate = (output_dir / filename).resolve()
        if candidate.parent == resolved_output and candidate.is_file():
            candidate.unlink()


def export_capcut_scenes(
    config: PipelineConfig,
    rows: list[dict],
    output_dir: Path,
) -> Path:
    """Export adjacent, narration-aligned clips for a CapCut main track."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _remove_previous_generated_scenes(output_dir)
    manifest_rows = []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    width, height = config.resolution

    for index, row in enumerate(rows, start=1):
        source = Path(str(row["footage"]))
        if not source.is_file():
            raise FileNotFoundError(
                f"Footage đã chọn không còn tồn tại: {source}"
            )
        timeline_start = float(row["timeline_start"])
        timeline_end = float(row["timeline_end"])
        duration = timeline_end - timeline_start
        if duration <= 0:
            raise ValueError(
                f"Dòng Timeline {index} có thời lượng không hợp lệ"
            )

        visual_start = float(row.get("visual_start", timeline_start))
        source_start = float(row["source_start"])
        trim_start = max(
            0.0, source_start + max(0.0, timeline_start - visual_start)
        )
        beat_value = row.get("beats", [])
        beat_codes = (
            [str(code) for code in beat_value]
            if isinstance(beat_value, list)
            else str(beat_value).split("+")
        )
        beat_label = "+".join(beat_codes) or f"CUT{index:03d}"
        safe_source = re.sub(
            r"[^A-Za-z0-9_-]+", "-", source.stem
        ).strip("-")
        filename = f"{index:03d}_{beat_label}_{safe_source}.mp4"
        destination = output_dir / filename
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={config.output_fps},"
            f"tpad=stop_mode=clone:stop_duration={duration:.6f},"
            f"trim=duration={duration:.6f},setpts=PTS-STARTPTS"
        )
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", f"{trim_start:.6f}",
            "-i", str(source),
            "-t", f"{duration:.6f}",
            "-map", "0:v:0",
            "-an",
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", config.encoder_preset,
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(destination),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **hidden_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Không thể xuất Scene CapCut {index}: "
                f"{completed.stderr.strip() or 'FFmpeg thất bại'}"
            )
        manifest_rows.append(
            {
                "order": index,
                "beats": beat_label,
                "scene_file": filename,
                "timeline_start": round(timeline_start, 6),
                "timeline_end": round(timeline_end, 6),
                "duration": round(duration, 6),
                "source_file": source.name,
                "source_path": str(source),
                "source_start": round(trim_start, 6),
                "source_end": round(trim_start + duration, 6),
            }
        )
        print(
            f"Xuất Scene [{index}/{len(rows)}]: "
            f"{beat_label} -> {filename}"
        )

    manifest_path = output_dir / "selected_scenes.csv"
    with manifest_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(manifest_rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    return manifest_path
