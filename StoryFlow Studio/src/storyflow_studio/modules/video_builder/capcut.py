"""Portable CapCut package export from a saved StoryFlow timeline."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from ...core.settings import AppSettings
from ..workspace import Project


class CapCutExportError(RuntimeError):
    pass


class Cancellation(Protocol):
    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CapCutExportProgress:
    stage: str
    state: str
    percent: int | None
    message: str


@dataclass(frozen=True, slots=True)
class CapCutExportResult:
    package_dir: Path
    manifest_file: Path
    scene_count: int
    duration_seconds: float


class CapCutPackageExporter:
    def __init__(self, *, ffmpeg: str | None = None) -> None:
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""

    def export(
        self,
        project: Project,
        settings: AppSettings,
        rows: tuple[dict, ...],
        duration: float,
        progress: Callable[[CapCutExportProgress], None],
        cancellation: Cancellation,
        *,
        replace_existing: bool = False,
    ) -> CapCutExportResult:
        if not self.ffmpeg:
            raise CapCutExportError("CapCut Export cần cài ffmpeg.")
        if not rows:
            raise CapCutExportError("Timeline không có Cut để xuất CapCut.")
        package_dir = project.path_for("capcut_package_dir")
        if package_dir.exists() and not replace_existing:
            raise CapCutExportError(
                "CapCut Package đã tồn tại. Hãy dùng Export Again để thay thế."
            )
        config = settings.normalized().video_builder
        width, height = (1280, 720) if config.resolution == "720p" else (1920, 1080)
        package_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=".capcut-package-", dir=package_dir.parent)
        )
        backup = package_dir.with_name(f".{package_dir.name}.backup")
        try:
            scenes_dir = temporary / "scenes"
            scenes_dir.mkdir()
            manifest_rows: list[dict] = []
            progress(CapCutExportProgress("video_plan", "running", 2, "Preparing CapCut Package…"))
            for index, row in enumerate(rows, start=1):
                cancellation.raise_if_cancelled()
                exported = self._export_scene(
                    project, row, scenes_dir, index, width, height,
                    config.output_fps, config.encoder_preset,
                )
                manifest_rows.append(exported)
                percent = 5 + int(75 * index / len(rows))
                progress(
                    CapCutExportProgress(
                        "video_plan", "running", percent,
                        f"Exported CapCut scene {index}/{len(rows)}",
                    )
                )
            cancellation.raise_if_cancelled()
            media = self._copy_project_media(project, settings, temporary)
            self._write_scene_csv(temporary / "selected_scenes.csv", manifest_rows)
            manifest_file = temporary / "capcut_manifest.json"
            manifest_file.write_text(
                json.dumps(
                    {
                        "schema": "storyflow.capcut-package",
                        "schema_version": 1,
                        "created_utc": datetime.now(UTC).isoformat(),
                        "project": project.manifest.name,
                        "canvas": {
                            "width": width,
                            "height": height,
                            "fps": config.output_fps,
                            "duration_seconds": round(duration, 6),
                        },
                        "tracks": {
                            "video": manifest_rows,
                            "narration": media["narration"],
                            "captions": media["captions"],
                            "background_music": media["background_music"],
                            "reference_video": media["reference_video"],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            (temporary / "README_CAPCUT.txt").write_text(
                "STORYFLOW CAPCUT PACKAGE\n\n"
                "1. Import all MP4 files in scenes/ in filename order.\n"
                "2. Place narration audio at 00:00:00; do not trim it.\n"
                "3. Import captions.srt through CapCut Captions.\n"
                "4. Add background_music.mp3 when present.\n"
                "5. Use reference.mp4 to compare the finished timeline when present.\n"
                "6. capcut_manifest.json contains exact editable timing.\n",
                encoding="utf-8",
            )
            progress(CapCutExportProgress("video_plan", "running", 90, "Publishing CapCut Package…"))
            if backup.exists():
                shutil.rmtree(backup)
            if package_dir.exists():
                os.replace(package_dir, backup)
            try:
                os.replace(temporary, package_dir)
            except Exception:
                if backup.exists() and not package_dir.exists():
                    os.replace(backup, package_dir)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            progress(CapCutExportProgress("video_plan", "completed", 100, f"Created {package_dir.name}"))
            return CapCutExportResult(
                package_dir,
                package_dir / manifest_file.name,
                len(manifest_rows),
                duration,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise CapCutExportError(str(exc)) from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def _export_scene(
        self, project: Project, row: dict, scenes_dir: Path, index: int,
        width: int, height: int, fps: int, preset: str,
    ) -> dict:
        relative = Path(str(row.get("footage", "")))
        source = (project.root / relative).resolve()
        try:
            source.relative_to(project.root)
        except ValueError as exc:
            raise CapCutExportError(f"Cut {index} có footage ngoài Project.") from exc
        if not source.is_file():
            raise CapCutExportError(f"Cut {index} đang thiếu footage: {relative}")
        start = float(row.get("timeline_start", 0.0))
        end = float(row.get("timeline_end", start))
        scene_duration = end - start
        source_start = max(0.0, float(row.get("source_start", 0.0)))
        if scene_duration <= 0:
            raise CapCutExportError(f"Cut {index} có duration không hợp lệ.")
        beat = re.sub(r"[^A-Za-z0-9_-]+", "-", str(row.get("beat", "CUT"))).strip("-")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")
        filename = f"{index:03d}_{beat or 'CUT'}_{stem or 'scene'}.mp4"
        destination = scenes_dir / filename
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},"
            f"tpad=stop_mode=clone:stop_duration={scene_duration:.6f},"
            f"trim=duration={scene_duration:.6f},setpts=PTS-STARTPTS"
        )
        completed = subprocess.run(
            [
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{source_start:.6f}", "-i", str(source),
                "-t", f"{scene_duration:.6f}", "-map", "0:v:0", "-an",
                "-vf", video_filter, "-c:v", "libx264", "-preset", preset,
                "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise CapCutExportError(
                f"Không xuất được CapCut scene {index}: {completed.stderr[-1500:].strip()}"
            )
        return {
            "order": index,
            "beat": str(row.get("beat", "")),
            "file": f"scenes/{filename}",
            "timeline_start": round(start, 6),
            "timeline_end": round(end, 6),
            "duration": round(scene_duration, 6),
            "source_file": relative.as_posix(),
            "source_start": round(source_start, 6),
            "source_end": round(source_start + scene_duration, 6),
        }

    @staticmethod
    def _copy_project_media(project: Project, settings: AppSettings, target: Path) -> dict:
        narration = project.path_for("audio_file")
        captions = project.path_for("subtitle_file")
        if not narration.is_file() or not captions.is_file():
            raise CapCutExportError("CapCut Export cần narration MP3 và SRT.")
        narration_name = f"narration{narration.suffix.lower() or '.mp3'}"
        shutil.copy2(narration, target / narration_name)
        shutil.copy2(captions, target / "captions.srt")
        music_name = None
        music = project.path_for("background_music_file")
        if settings.normalized().music.enabled and music.is_file():
            music_name = f"background_music{music.suffix.lower() or '.mp3'}"
            shutil.copy2(music, target / music_name)
        reference_name = None
        reference = project.path_for("final_video_file")
        if reference.is_file():
            reference_name = "reference.mp4"
            shutil.copy2(reference, target / reference_name)
        return {
            "narration": narration_name,
            "captions": "captions.srt",
            "background_music": music_name,
            "reference_video": reference_name,
        }

    @staticmethod
    def _write_scene_csv(path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
