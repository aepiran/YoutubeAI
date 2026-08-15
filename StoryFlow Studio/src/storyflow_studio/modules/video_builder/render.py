"""Low-memory FFmpeg timeline renderer with atomic project outputs."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ...core.settings import AppSettings
from ..workspace import Project


class VideoRenderError(RuntimeError):
    pass


class Cancellation(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VideoRenderProgress:
    stage: str
    state: str
    percent: int | None
    message: str


@dataclass(frozen=True, slots=True)
class VideoRenderResult:
    final_file: Path
    attribution_file: Path
    duration_seconds: float
    size_bytes: int
    cut_count: int


ProgressCallback = Callable[[VideoRenderProgress], None]
DiskUsage = Callable[[Path], object]


class FFmpegTimelineRenderer:
    def __init__(
        self,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        disk_usage: DiskUsage = shutil.disk_usage,
    ) -> None:
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""
        self.ffprobe = ffprobe or shutil.which("ffprobe") or ""
        self.disk_usage = disk_usage

    def render(
        self,
        project: Project,
        settings: AppSettings,
        rows: tuple[dict, ...],
        duration: float,
        progress: ProgressCallback,
        cancellation: Cancellation,
        *,
        replace_existing: bool = False,
    ) -> VideoRenderResult:
        if not self.ffmpeg or not self.ffprobe:
            raise VideoRenderError("Final Render cần cài ffmpeg và ffprobe.")
        final_file = project.path_for("final_video_file")
        attribution_file = project.path_for("attribution_file")
        if final_file.exists() and not replace_existing:
            raise VideoRenderError(
                "Final video đã tồn tại. Hãy dùng Render Again để tạo lại."
            )
        _validate_rows(project, rows, duration)
        narration = project.path_for("audio_file")
        if not narration.is_file():
            raise VideoRenderError("Thiếu narration MP3 để Final Render.")
        config = settings.normalized()
        width, height = (1280, 720) if config.video_builder.resolution == "720p" else (1920, 1080)
        required_bytes = max(
            512 * 1024 * 1024,
            int(duration * (1_500_000 if height == 1080 else 900_000)),
        )
        free = int(getattr(self.disk_usage(project.root), "free", 0))
        if free < required_bytes:
            raise VideoRenderError(
                "Không đủ dung lượng render tạm: cần khoảng "
                f"{required_bytes / (1024 ** 3):.2f} GB, còn "
                f"{free / (1024 ** 3):.2f} GB."
            )
        cancellation.raise_if_cancelled()
        progress(VideoRenderProgress("video_plan", "running", 2, "Validating render inputs…"))
        cache_root = project.metadata_dir / "cache" / "video-builder"
        cache_root.mkdir(parents=True, exist_ok=True)
        final_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="render-", dir=cache_root) as directory:
            root = Path(directory)
            segments: list[Path] = []
            for index, row in enumerate(rows, start=1):
                cancellation.raise_if_cancelled()
                segment = root / f"segment-{index:05d}.mp4"
                self._render_cut(
                    project,
                    row,
                    segment,
                    width,
                    height,
                    config.video_builder.output_fps,
                    config.video_builder.encoder_preset,
                    cancellation,
                )
                segments.append(segment)
                percent = 5 + int(68 * index / len(rows))
                progress(
                    VideoRenderProgress(
                        "video_plan",
                        "running",
                        percent,
                        f"Rendered Cut {index}/{len(rows)}",
                    )
                )
            concat = root / "concat.txt"
            concat.write_text(
                "\n".join(f"file '{_concat_escape(path)}'" for path in segments) + "\n",
                encoding="utf-8",
            )
            temporary_final = root / "final-video.mp4"
            music = project.path_for("background_music_file")
            use_music = config.music.enabled and music.is_file()
            progress(
                VideoRenderProgress(
                    "video_plan",
                    "running",
                    76,
                    "Muxing narration" + (" and background music…" if use_music else "…"),
                )
            )
            self._mux_audio(
                concat,
                narration,
                music if use_music else None,
                temporary_final,
                duration,
                cancellation,
            )
            progress(VideoRenderProgress("video_plan", "running", 94, "Validating final media…"))
            actual_duration = self._validate_media(
                temporary_final, duration, width, height
            )
            temporary_attribution = root / "attribution.csv"
            _write_attribution(temporary_attribution, project, rows)
            previous_attribution = (
                attribution_file.read_bytes() if attribution_file.is_file() else None
            )
            try:
                _atomic_copy(temporary_attribution, attribution_file)
                os.replace(temporary_final, final_file)
            except Exception:
                if previous_attribution is None:
                    attribution_file.unlink(missing_ok=True)
                else:
                    _atomic_bytes(attribution_file, previous_attribution)
                raise
        progress(
            VideoRenderProgress(
                "video_plan", "completed", 100, f"Created {final_file.name}"
            )
        )
        return VideoRenderResult(
            final_file,
            attribution_file,
            actual_duration,
            final_file.stat().st_size,
            len(rows),
        )

    def _render_cut(
        self,
        project: Project,
        row: dict,
        output: Path,
        width: int,
        height: int,
        fps: int,
        preset: str,
        cancellation: Cancellation,
    ) -> None:
        source = (project.root / str(row["footage"])).resolve()
        duration = float(row["duration"])
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{float(row['source_start']):.6f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.6f}",
            "-an",
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={fps},format=yuv420p,setpts=PTS-STARTPTS"
            ),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(output),
        ]
        _run_cancellable(command, cancellation, f"Không render được {source.name}")

    def _mux_audio(
        self,
        concat: Path,
        narration: Path,
        music: Path | None,
        output: Path,
        duration: float,
        cancellation: Cancellation,
    ) -> None:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(narration),
        ]
        if music is not None:
            command.extend(["-stream_loop", "-1", "-i", str(music)])
            command.extend(
                [
                    "-filter_complex",
                    (
                        "[1:a]aresample=48000[voice];"
                        f"[2:a]aresample=48000,apad,atrim=0:{duration:.6f}[music];"
                        "[voice][music]amix=inputs=2:duration=first:normalize=0[aout]"
                    ),
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                ]
            )
        else:
            command.extend(["-map", "0:v:0", "-map", "1:a:0"])
        command.extend(
            [
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        _run_cancellable(command, cancellation, "FFmpeg không mux được final video")

    def _validate_media(
        self, path: Path, expected_duration: float, width: int, height: int
    ) -> float:
        try:
            result = subprocess.run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            video = next(item for item in streams if item.get("codec_type") == "video")
            audio = next(item for item in streams if item.get("codec_type") == "audio")
            duration = float(payload["format"]["duration"])
            audio_duration = float(audio["duration"])
        except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise VideoRenderError(f"Final media validation thất bại: {exc}") from exc
        if int(video.get("width") or 0) != width or int(video.get("height") or 0) != height:
            raise VideoRenderError("Final video resolution không đúng Settings.")
        if duration + 0.15 < expected_duration or audio_duration + 0.15 < expected_duration:
            raise VideoRenderError("Final video bị thiếu narration duration.")
        return duration


def _validate_rows(project: Project, rows: tuple[dict, ...], duration: float) -> None:
    if not rows:
        raise VideoRenderError("Timeline không có Cut để render.")
    previous_end = 0.0
    for position, row in enumerate(rows, start=1):
        try:
            start = float(row["timeline_start"])
            end = float(row["timeline_end"])
            source_start = float(row["source_start"])
            source_end = float(row["source_end"])
            footage = (project.root / str(row["footage"])).resolve(strict=True)
            footage.relative_to(project.root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VideoRenderError(f"Cut {position} có source không hợp lệ.") from exc
        warnings = set(row.get("warnings", []))
        if "missing_footage" in warnings or not row.get("footage"):
            raise VideoRenderError(f"Cut {position} đang thiếu footage.")
        if abs(start - previous_end) > 0.05 or end <= start:
            raise VideoRenderError(f"Timeline không liên tục tại Cut {position}.")
        if source_start < 0 or source_end - source_start + 0.02 < end - start:
            raise VideoRenderError(f"Source window không đủ cho Cut {position}.")
        previous_end = end
    if abs(previous_end - duration) > 0.05:
        raise VideoRenderError("Timeline không phủ đủ narration duration.")


def _run_cancellable(command: list[str], cancellation: Cancellation, label: str) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        while True:
            try:
                _stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancellation.cancelled:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    cancellation.raise_if_cancelled()
        if process.returncode != 0:
            raise VideoRenderError(f"{label}: {stderr[-2000:].strip()}")
    finally:
        if process.poll() is None:
            process.kill()


def _write_attribution(path: Path, project: Project, rows: tuple[dict, ...]) -> None:
    metadata: dict[str, dict] = {}
    manifest = project.path_for("footage_manifest")
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            metadata = {
                str(item.get("filename", "")): item
                for item in payload.get("selections", [])
                if isinstance(item, dict)
            }
        except (OSError, json.JSONDecodeError):
            metadata = {}
    grouped: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        footage = str(row.get("footage", ""))
        item = grouped.setdefault(footage, {"beats": set(), "cuts": set()})
        item["beats"].add(str(row.get("beat", "")))
        item["cuts"].add(str(row.get("cut", "")))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        columns = (
            "footage",
            "provider",
            "video_id",
            "contributor",
            "source_url",
            "beats",
            "cuts",
        )
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for footage, usage in grouped.items():
            source = metadata.get(Path(footage).name, {})
            writer.writerow(
                {
                    "footage": footage,
                    "provider": source.get("provider", "local"),
                    "video_id": source.get("video_id", ""),
                    "contributor": source.get("contributor", ""),
                    "source_url": source.get("page_url", ""),
                    "beats": "|".join(sorted(usage["beats"])),
                    "cuts": "|".join(sorted(usage["cuts"], key=lambda value: int(value))),
                }
            )


def _concat_escape(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with source.open("rb") as input_handle, handle:
            shutil.copyfileobj(input_handle, handle)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=path.parent)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
