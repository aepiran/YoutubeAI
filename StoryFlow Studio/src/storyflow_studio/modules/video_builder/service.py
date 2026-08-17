"""Draft timeline analysis reusing validated Beat and Footage artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from ...core.media import MediaInfo, probe_audio_duration, probe_media_info
from ...core.settings import AppSettings, VideoBuilderSettings
from ..workspace import Project
from .visual import (
    FFmpegSceneDetector,
    SceneDetector,
    SceneRange,
    SemanticScorer,
    VisualAnalysisError,
    build_semantic_scorer,
)
from .render import FFmpegTimelineRenderer, VideoRenderError, VideoRenderResult
from .capcut import (
    CapCutExportError,
    CapCutExportResult,
    CapCutPackageExporter,
)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SCENE_CACHE_SCHEMA_VERSION = 2
TIMELINE_COLUMNS = (
    "cut",
    "beat",
    "timeline_start",
    "timeline_end",
    "duration",
    "footage",
    "source_start",
    "source_end",
    "technical_score",
    "source_width",
    "source_height",
    "scene_index",
    "semantic_score",
    "selection_score",
    "warnings",
)


class VideoBuilderWorkflowError(RuntimeError):
    pass


class Cancellation(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VideoBuilderProgress:
    stage: str
    state: str
    percent: int | None
    message: str


@dataclass(frozen=True, slots=True)
class TimelineAnalysisResult:
    timeline_file: Path
    timeline_csv: Path
    cut_count: int
    warning_count: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class TimelineReviewResult:
    timeline_file: Path
    rows: tuple[dict, ...]
    cut_count: int
    warning_count: int
    missing_beats: tuple[str, ...]
    stale: bool
    status: str


@dataclass(frozen=True, slots=True)
class _Source:
    path: Path
    duration: float
    duration_verified: bool
    width: int = 0
    height: int = 0
    technical_score: float = 0.0
    scenes: tuple[SceneRange, ...] = ()
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class _SceneOption:
    source: _Source
    scene_index: int
    start: float
    end: float

    @property
    def key(self) -> tuple[Path, float, float]:
        return (self.source.path, self.start, self.end)


@dataclass(frozen=True, slots=True)
class _Cut:
    cut: int
    beat: str
    narration: str
    timeline_start: float
    timeline_end: float
    duration: float
    footage: str
    source_start: float
    source_end: float
    technical_score: float
    source_width: int
    source_height: int
    scene_index: int
    semantic_score: float | None
    selection_score: float
    warnings: tuple[str, ...]

    def csv_row(self) -> dict[str, str | int | float]:
        row = asdict(self)
        row["warnings"] = " | ".join(self.warnings)
        row.pop("narration", None)
        return row


DurationProbe = Callable[[Path], float | None]
MediaProbe = Callable[[Path], MediaInfo | None]
SemanticScorerFactory = Callable[[str, Path, bool], SemanticScorer | None]


class VideoBuilderService:
    """Analyze, review, override and render the canonical video timeline."""

    def __init__(
        self,
        duration_probe: DurationProbe = probe_audio_duration,
        media_probe: MediaProbe = probe_media_info,
        scene_detector: SceneDetector | None = None,
        semantic_scorer_factory: SemanticScorerFactory = build_semantic_scorer,
        renderer: FFmpegTimelineRenderer | None = None,
        capcut_exporter: CapCutPackageExporter | None = None,
    ) -> None:
        self.duration_probe = duration_probe
        self.media_probe = media_probe
        self.scene_detector = scene_detector or FFmpegSceneDetector()
        self.semantic_scorer_factory = semantic_scorer_factory
        self.renderer = renderer or FFmpegTimelineRenderer()
        self.capcut_exporter = capcut_exporter or CapCutPackageExporter()

    def analyze(
        self,
        project: Project,
        settings: AppSettings,
        progress: Callable[[VideoBuilderProgress], None],
        cancellation: Cancellation,
        *,
        replace_existing: bool = False,
    ) -> TimelineAnalysisResult:
        config = settings.normalized().video_builder
        timeline_file = project.path_for("video_timeline_file")
        timeline_csv = project.path_for("video_timeline_csv")
        if (timeline_file.exists() or timeline_csv.exists()) and not replace_existing:
            raise VideoBuilderWorkflowError(
                "Timeline analysis đã tồn tại. Hãy dùng Analyze Again để chạy lại."
            )
        previous_outputs = {
            path: path.read_bytes() if path.is_file() else None
            for path in (timeline_file, timeline_csv)
        }
        progress(
            VideoBuilderProgress(
                "video_plan", "running", 5, "Validating reusable stage artifacts…"
            )
        )
        cancellation.raise_if_cancelled()
        timing = _load_timing(project)
        _verify_timing_sources(project, timing)
        beats = timing["beats"]
        duration = float(timing["duration_seconds"])
        try:
            semantic_scorer = self.semantic_scorer_factory(
                config.visual_model,
                project.metadata_dir / "cache" / "vision-models",
                config.local_models_only,
            )
        except VisualAnalysisError as exc:
            raise VideoBuilderWorkflowError(str(exc)) from exc
        inventory = _load_inventory(
            project,
            beats,
            self.duration_probe,
            self.media_probe,
            self.scene_detector,
            config,
            progress,
            cancellation,
        )
        semantics = _load_beat_semantics(project.path_for("beat_file"))
        progress(
            VideoBuilderProgress(
                "video_plan",
                "running",
                25,
                f"Reused SRT timing · {len(beats)} beats · "
                f"{sum(len(items) for items in inventory.values())} clips",
            )
        )
        cuts: list[_Cut] = []
        history: list[tuple[Path, float, float]] = []
        for position, beat in enumerate(beats, start=1):
            cancellation.raise_if_cancelled()
            code = str(beat["code"]).upper()
            sources = inventory.get(code, [])
            beat_semantics = semantics.get(code, {})
            cached_plan = _load_plan_cache(
                project,
                beat,
                sources,
                config,
                beat_semantics,
                semantic_scorer.model_name if semantic_scorer is not None else "",
                history,
                len(cuts),
            )
            if cached_plan is not None:
                planned, cached_history = cached_plan
                cuts.extend(planned)
                history.extend(cached_history)
                action = "Reused plan"
            else:
                history_start = len(history)
                planned = _plan_beat(
                    project,
                    beat,
                    sources,
                    config,
                    len(cuts),
                    beat_semantics,
                    semantic_scorer,
                    history,
                )
                cuts.extend(planned)
                _write_plan_cache(
                    project,
                    beat,
                    sources,
                    config,
                    beat_semantics,
                    semantic_scorer.model_name if semantic_scorer is not None else "",
                    history[:history_start],
                    planned,
                    history[history_start:],
                )
                action = "Planned"
            percent = 25 + int(55 * position / max(1, len(beats)))
            progress(
                VideoBuilderProgress(
                    "video_plan",
                    "running",
                    percent,
                    f"{action} {beat['code']} · {position}/{len(beats)} beats",
                )
            )
        if not cuts:
            raise VideoBuilderWorkflowError("Không tạo được Cut nào từ Beat timing.")
        cancellation.raise_if_cancelled()
        warning_count = sum(len(cut.warnings) for cut in cuts)
        payload = {
            "schema_version": 2,
            "created_at": datetime.now(UTC).isoformat(),
            "analysis_mode": "technical_review",
            "status": "review_required" if warning_count else "draft_ready",
            "render_supported": False,
            "visual_ai_scoring": semantic_scorer is not None,
            "visual_model": config.visual_model,
            "technical_scoring": True,
            "project_id": project.manifest.project_id,
            "duration_seconds": round(duration, 6),
            "cut_count": len(cuts),
            "warning_count": warning_count,
            "settings": asdict(config),
            "input_fingerprint": _input_fingerprint(project, config),
            "timeline": [asdict(cut) for cut in cuts],
            "notes": [
                "Timing reused from Beat DNA and narration SRT.",
                "Footage assignment reused from Footage Finder filenames/manifest.",
                "Technical compatibility scoring is enabled (duration/resolution/orientation).",
                (
                    f"Semantic scoring enabled with {config.visual_model}."
                    if semantic_scorer is not None
                    else "Semantic scoring disabled; technical-only optimization used."
                ),
                "Final MP4 rendering is pending Phase 7B3.",
            ],
        }
        progress(
            VideoBuilderProgress(
                "video_plan", "running", 90, "Writing timeline JSON and CSV atomically…"
            )
        )
        try:
            _atomic_json(timeline_file, payload)
            _atomic_csv(timeline_csv, cuts)
        except Exception:
            _restore_outputs(previous_outputs)
            raise
        message = f"Created {len(cuts)} cuts · {warning_count} warnings"
        progress(VideoBuilderProgress("video_plan", "completed", 100, message))
        return TimelineAnalysisResult(
            timeline_file, timeline_csv, len(cuts), warning_count, duration
        )

    def clear_analysis_cache(self, project: Project) -> int:
        """Remove reusable Video Builder analysis caches for one project."""
        return _clear_analysis_cache(project)

    def review(
        self, project: Project, settings: AppSettings
    ) -> TimelineReviewResult:
        """Load a timeline for UI review and detect changes to its inputs."""
        path = project.path_for("video_timeline_file")
        if not path.is_file():
            raise VideoBuilderWorkflowError(
                "Chưa có timeline. Hãy chạy Analyze trước khi Review."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VideoBuilderWorkflowError(f"Timeline không hợp lệ: {exc}") from exc
        rows = payload.get("timeline") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in {1, 2}
            or not isinstance(rows, list)
        ):
            raise VideoBuilderWorkflowError("Timeline schema không được hỗ trợ.")
        normalized_rows = tuple(row for row in rows if isinstance(row, dict))
        if len(normalized_rows) != len(rows):
            raise VideoBuilderWorkflowError("Timeline chứa Cut không hợp lệ.")
        config = settings.normalized().video_builder
        stale = str(payload.get("input_fingerprint", "")) != _input_fingerprint(
            project, config
        )
        missing_beats = tuple(
            dict.fromkeys(
                str(row.get("beat", ""))
                for row in normalized_rows
                if "missing_footage" in row.get("warnings", [])
            )
        )
        warning_count = sum(
            len(row.get("warnings", []))
            for row in normalized_rows
            if isinstance(row.get("warnings", []), list)
        )
        status = "stale" if stale else str(payload.get("status", "review_required"))
        return TimelineReviewResult(
            path,
            normalized_rows,
            len(normalized_rows),
            warning_count,
            tuple(code for code in missing_beats if code),
            stale,
            status,
        )

    def replace_clip(
        self,
        project: Project,
        settings: AppSettings,
        cut_number: int,
        footage_path: Path,
    ) -> TimelineReviewResult:
        """Apply a manual, project-local footage override to one reviewed Cut."""
        review = self.review(project, settings)
        if review.stale:
            raise VideoBuilderWorkflowError(
                "Timeline đã stale. Hãy Analyze Again trước khi Replace Clip."
            )
        try:
            footage_path = footage_path.resolve(strict=True)
            footage_path.relative_to(project.path_for("footage_dir").resolve())
        except (OSError, ValueError) as exc:
            raise VideoBuilderWorkflowError(
                "Replace Clip chỉ nhận video nằm trong Project video folder."
            ) from exc
        if footage_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise VideoBuilderWorkflowError("Định dạng Replace Clip không được hỗ trợ.")
        timeline_file = project.path_for("video_timeline_file")
        timeline_csv = project.path_for("video_timeline_csv")
        payload = json.loads(timeline_file.read_text(encoding="utf-8"))
        target = next(
            (
                row
                for row in payload.get("timeline", [])
                if int(row.get("cut", -1)) == int(cut_number)
            ),
            None,
        )
        if target is None:
            raise VideoBuilderWorkflowError(f"Không tìm thấy Cut {cut_number}.")
        config = settings.normalized().video_builder
        duration = self.duration_probe(footage_path)
        metadata = _manifest_metadata(project.path_for("footage_manifest")).get(
            footage_path.name, {}
        )
        duration = duration or float(metadata.get("duration") or 0)
        required = float(target.get("duration") or 0)
        if duration <= 0 or duration + 0.02 < required:
            raise VideoBuilderWorkflowError(
                f"Clip thay thế cần ít nhất {required:.2f}s usable duration."
            )
        width = int(metadata.get("width") or 0)
        height = int(metadata.get("height") or 0)
        scenes = self.scene_detector.detect(
            footage_path, duration, config.scene_threshold, config.scene_min_seconds
        )
        scene = next((item for item in scenes if item.end - item.start >= required), scenes[0])
        target.update(
            {
                "footage": footage_path.relative_to(project.root).as_posix(),
                "source_start": round(scene.start, 6),
                "source_end": round(min(scene.end, scene.start + required), 6),
                "technical_score": _technical_score(
                    self.duration_probe(footage_path) is not None,
                    width,
                    height,
                    config,
                ),
                "source_width": width,
                "source_height": height,
                "scene_index": scene.index,
                "semantic_score": None,
                "selection_score": 0.0,
                "warnings": ["manual_replacement_pending_semantic_review"],
            }
        )
        payload["status"] = "review_required"
        payload["warning_count"] = sum(
            len(row.get("warnings", [])) for row in payload.get("timeline", [])
        )
        overrides = payload.setdefault("manual_overrides", [])
        overrides.append(
            {
                "cut": int(cut_number),
                "footage": target["footage"],
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        previous = {
            path: path.read_bytes() if path.is_file() else None
            for path in (timeline_file, timeline_csv)
        }
        try:
            _atomic_json(timeline_file, payload)
            _atomic_csv_rows(timeline_csv, payload["timeline"])
        except Exception:
            _restore_outputs(previous)
            raise
        return self.review(project, settings)

    def render(
        self,
        project: Project,
        settings: AppSettings,
        progress: Callable[[object], None],
        cancellation: Cancellation,
        *,
        replace_existing: bool = False,
    ) -> VideoRenderResult:
        review = self.review(project, settings)
        try:
            payload = json.loads(review.timeline_file.read_text(encoding="utf-8"))
            duration = float(payload["duration_seconds"])
            return self.renderer.render(
                project,
                settings,
                review.rows,
                duration,
                progress,
                cancellation,
                replace_existing=replace_existing,
            )
        except VideoBuilderWorkflowError:
            raise
        except VideoRenderError as exc:
            raise VideoBuilderWorkflowError(str(exc)) from exc

    def export_capcut(
        self,
        project: Project,
        settings: AppSettings,
        progress: Callable[[object], None],
        cancellation: Cancellation,
        *,
        replace_existing: bool = False,
        draft_name: str | None = None,
    ) -> CapCutExportResult:
        review = self.review(project, settings)
        if review.missing_beats:
            raise VideoBuilderWorkflowError(
                "CapCut Export còn thiếu footage: " + ", ".join(review.missing_beats)
            )
        try:
            payload = json.loads(review.timeline_file.read_text(encoding="utf-8"))
            duration = float(payload["duration_seconds"])
            return self.capcut_exporter.export(
                project,
                settings,
                review.rows,
                duration,
                progress,
                cancellation,
                replace_existing=replace_existing,
                draft_name=draft_name,
            )
        except CapCutExportError as exc:
            raise VideoBuilderWorkflowError(str(exc)) from exc


def _load_timing(project: Project) -> dict:
    path = project.path_for("beat_timing_file")
    if not path.is_file():
        raise VideoBuilderWorkflowError(
            "Thiếu .storyflow/beat_timing.json. Hãy tạo lại Beat DNA để lưu "
            "validated SRT timing cho Video Builder."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VideoBuilderWorkflowError(f"Beat timing không hợp lệ: {exc}") from exc
    if not isinstance(payload, dict):
        raise VideoBuilderWorkflowError("Beat timing schema không được hỗ trợ.")
    beats = payload.get("beats")
    if payload.get("schema_version") != 1 or not isinstance(beats, list) or not beats:
        raise VideoBuilderWorkflowError("Beat timing schema không được hỗ trợ.")
    previous_end = 0.0
    for position, beat in enumerate(beats, start=1):
        try:
            code = str(beat["code"]).upper()
            start = float(beat["start_seconds"])
            end = float(beat["end_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VideoBuilderWorkflowError(
                f"Beat timing dòng {position} không hợp lệ."
            ) from exc
        if (
            code != f"H{position:02d}"
            or abs(start - previous_end) > 0.05
            or end <= start
        ):
            raise VideoBuilderWorkflowError(
                f"Beat timing không liên tục tại {code or position}."
            )
        previous_end = end
    try:
        duration = float(payload["duration_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoBuilderWorkflowError("Beat timing thiếu narration duration.") from exc
    if duration <= 0 or abs(previous_end - duration) > 0.05:
        raise VideoBuilderWorkflowError(
            "Beat timing chưa phủ liên tục toàn bộ narration duration."
        )
    return payload


def _verify_timing_sources(project: Project, timing: dict) -> None:
    sources = timing.get("sources")
    if not isinstance(sources, dict):
        raise VideoBuilderWorkflowError("Beat timing thiếu source fingerprints.")
    for path_name, hash_name, project_key in (
        ("script", "script_sha256", "tts_script"),
        ("subtitle", "subtitle_sha256", "subtitle_file"),
        ("beat_csv", "beat_csv_sha256", "beat_file"),
    ):
        path = project.path_for(project_key)
        if not path.is_file() or _sha256(path) != str(sources.get(hash_name, "")):
            raise VideoBuilderWorkflowError(
                f"{path.name} đã thay đổi sau Beat DNA; hãy tạo lại Beat timing."
            )
        try:
            relative = path.relative_to(project.root).as_posix()
        except ValueError as exc:
            raise VideoBuilderWorkflowError("Beat timing source thoát project.") from exc
        if str(sources.get(path_name, "")).replace("\\", "/") != relative:
            raise VideoBuilderWorkflowError(
                f"Beat timing không trỏ đúng canonical {path.name}."
            )


def _load_inventory(
    project: Project,
    beats: list[dict],
    duration_probe: DurationProbe,
    media_probe: MediaProbe,
    scene_detector: SceneDetector,
    config: VideoBuilderSettings,
    progress: Callable[[VideoBuilderProgress], None],
    cancellation: Cancellation,
) -> dict[str, list[_Source]]:
    known = {str(beat["code"]).upper() for beat in beats}
    manifest_metadata = _manifest_metadata(project.path_for("footage_manifest"))
    inventory_cache = _load_inventory_cache(project)
    result = {code: [] for code in known}
    directory = project.path_for("footage_dir")
    if not directory.is_dir():
        return result
    candidates: list[tuple[Path, str]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        code = _filename_beat(path, known)
        if code is None:
            continue
        candidates.append((path, code))
    if not candidates:
        return result

    cancellation.raise_if_cancelled()
    inspected: list[tuple[str, _Source] | None] = [None] * len(candidates)
    cache_entries: dict[str, dict] = {}
    pending: list[
        tuple[
            int,
            Path,
            str,
            str,
            str,
            dict | None,
            tuple[SceneRange, ...] | None,
        ]
    ] = []
    completed = 0
    for index, (path, code) in enumerate(candidates):
        relative = path.relative_to(project.root).as_posix()
        item_metadata = manifest_metadata.get(path.name, {})
        fingerprint = _footage_fingerprint(path, relative, item_metadata)
        cached_metadata = _cached_inventory_entry(
            inventory_cache.get(relative), fingerprint, config
        )
        cached_scenes = (
            _load_scene_cache(project, fingerprint, config)
            if cached_metadata is not None
            else None
        )
        if cached_metadata is not None and cached_scenes is not None:
            inspected[index] = (
                code,
                _source_from_inventory_entry(path, cached_metadata, cached_scenes, config),
            )
            cache_entries[relative] = cached_metadata
            completed += 1
            _report_inventory_progress(
                progress, completed, len(candidates), path, cached=True
            )
        else:
            if cached_metadata is not None:
                cache_entries[relative] = cached_metadata
            pending.append(
                (
                    index,
                    path,
                    code,
                    relative,
                    fingerprint,
                    cached_metadata,
                    cached_scenes,
                )
            )

    try:
        if pending:
            worker_count = min(config.analysis_workers, len(pending))
            progress(
                VideoBuilderProgress(
                    "video_plan",
                    "running",
                    5 + int(20 * completed / len(candidates)),
                    f"Scanning {len(pending)} footage · {worker_count} workers",
                )
            )
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="storyflow-analysis",
            ) as executor:
                futures = {
                    executor.submit(
                        _inspect_inventory_source,
                        path,
                        fingerprint,
                        manifest_metadata.get(path.name, {}),
                        cached_metadata,
                        cached_scenes,
                        duration_probe,
                        media_probe,
                        scene_detector,
                        config,
                        cancellation,
                    ): (
                        index,
                        code,
                        path,
                        relative,
                        fingerprint,
                        cached_scenes,
                    )
                    for (
                        index,
                        path,
                        code,
                        relative,
                        fingerprint,
                        cached_metadata,
                        cached_scenes,
                    ) in pending
                }
                for future in as_completed(futures):
                    cancellation.raise_if_cancelled()
                    index, code, path, relative, fingerprint, cached_scenes = futures[
                        future
                    ]
                    source, entry = future.result()
                    inspected[index] = (code, source)
                    cache_entries[relative] = entry
                    if cached_scenes is None:
                        _write_scene_cache(project, fingerprint, config, source.scenes)
                    completed += 1
                    _report_inventory_progress(
                        progress, completed, len(candidates), path, cached=False
                    )
    finally:
        if cache_entries:
            _write_inventory_cache(project, cache_entries)

    # Futures complete out of order; append by the original sorted path order so
    # identical inputs continue to produce deterministic timeline candidates.
    for item in inspected:
        if item is not None:
            code, source = item
            result[code].append(source)
    return result


def _inspect_inventory_source(
    path: Path,
    fingerprint: str,
    manifest_metadata: dict[str, float | int],
    cached_metadata: dict | None,
    cached_scenes: tuple[SceneRange, ...] | None,
    duration_probe: DurationProbe,
    media_probe: MediaProbe,
    scene_detector: SceneDetector,
    config: VideoBuilderSettings,
    cancellation: Cancellation,
) -> tuple[_Source, dict]:
    if cached_metadata is not None:
        entry = cached_metadata
    else:
        media = media_probe(path)
        probed_duration = media.duration if media is not None else duration_probe(path)
        manifest_duration = manifest_metadata.get("duration")
        duration = max(
            0.1,
            float(
                probed_duration
                or manifest_duration
                or config.max_cut_seconds
            ),
        )
        width = int(
            (media.width if media is not None else 0)
            or manifest_metadata.get("width")
            or 0
        )
        height = int(
            (media.height if media is not None else 0)
            or manifest_metadata.get("height")
            or 0
        )
        entry = {
            "fingerprint": fingerprint,
            "duration": duration,
            "duration_verified": probed_duration is not None,
            "duration_source": (
                "probe"
                if probed_duration is not None
                else "manifest"
                if manifest_duration
                else "estimate"
            ),
            "width": width,
            "height": height,
            "fps": media.fps if media is not None else 0.0,
            "codec": media.codec if media is not None else "",
        }
    duration = float(entry["duration"])
    scenes = cached_scenes
    if scenes is None:
        try:
            if isinstance(scene_detector, FFmpegSceneDetector):
                scenes = scene_detector.detect(
                    path,
                    duration,
                    config.scene_threshold,
                    config.scene_min_seconds,
                    cancellation=cancellation,
                )
            else:
                scenes = scene_detector.detect(
                    path,
                    duration,
                    config.scene_threshold,
                    config.scene_min_seconds,
                )
        except (OSError, ValueError, VisualAnalysisError):
            scenes = (SceneRange(0, 0.0, duration),)
    return _source_from_inventory_entry(path, entry, scenes, config), entry


def _source_from_inventory_entry(
    path: Path,
    entry: dict,
    scenes: tuple[SceneRange, ...],
    config: VideoBuilderSettings,
) -> _Source:
    duration = max(0.1, float(entry["duration"]))
    verified = bool(entry.get("duration_verified", False))
    width = max(0, int(entry.get("width") or 0))
    height = max(0, int(entry.get("height") or 0))
    return _Source(
        path,
        duration,
        verified,
        width,
        height,
        _technical_score(verified, width, height, config),
        scenes,
        str(entry.get("fingerprint") or ""),
    )


def _report_inventory_progress(
    progress: Callable[[VideoBuilderProgress], None],
    completed: int,
    total: int,
    path: Path,
    *,
    cached: bool,
) -> None:
    percent = 5 + int(20 * completed / max(1, total))
    action = "Cached" if cached else "Analyzed"
    progress(
        VideoBuilderProgress(
            "video_plan",
            "running",
            percent,
            f"{action} footage {completed}/{total} · {path.name}",
        )
    )


def _footage_fingerprint(
    path: Path, relative: str, manifest_metadata: dict[str, float | int]
) -> str:
    stat = path.stat()
    payload = {
        "path": relative,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "manifest": manifest_metadata,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _analysis_cache_root(project: Project) -> Path:
    return project.metadata_dir / "video-builder" / "cache"


def _clear_analysis_cache(project: Project) -> int:
    root = _analysis_cache_root(project)
    try:
        resolved_root = root.resolve()
        resolved_metadata = project.metadata_dir.resolve()
        resolved_root.relative_to(resolved_metadata)
    except (OSError, ValueError) as exc:
        raise VideoBuilderWorkflowError("Video Builder cache path không hợp lệ.") from exc
    if not root.exists():
        return 0
    if not root.is_dir():
        raise VideoBuilderWorkflowError("Video Builder cache path không phải thư mục.")
    removed = sum(1 for path in root.rglob("*") if path.is_file())
    shutil.rmtree(root)
    return removed


def _load_inventory_cache(project: Project) -> dict[str, dict]:
    path = _analysis_cache_root(project) / "inventory.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}
    entries = payload.get("entries")
    return entries if isinstance(entries, dict) else {}


def _cached_inventory_entry(
    value: object, fingerprint: str, config: VideoBuilderSettings
) -> dict | None:
    if not isinstance(value, dict) or value.get("fingerprint") != fingerprint:
        return None
    try:
        duration = float(value["duration"])
        width = int(value.get("width") or 0)
        height = int(value.get("height") or 0)
        fps = float(value.get("fps") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if duration <= 0 or width < 0 or height < 0 or fps < 0:
        return None
    duration_source = str(value.get("duration_source") or "")
    if duration_source not in {"probe", "manifest", "estimate"}:
        return None
    if duration_source == "estimate" and abs(duration - config.max_cut_seconds) > 0.001:
        return None
    return {
        "fingerprint": fingerprint,
        "duration": duration,
        "duration_verified": bool(value.get("duration_verified", False)),
        "duration_source": duration_source,
        "width": width,
        "height": height,
        "fps": fps,
        "codec": str(value.get("codec") or ""),
    }


def _write_inventory_cache(project: Project, entries: dict[str, dict]) -> None:
    _atomic_json(
        _analysis_cache_root(project) / "inventory.json",
        {"schema_version": 1, "entries": entries},
    )


def _scene_cache_path(
    project: Project, fingerprint: str, config: VideoBuilderSettings
) -> Path:
    settings_key = hashlib.sha256(
        (
            f"{config.scene_threshold:.6f}:"
            f"{config.scene_min_seconds:.6f}"
        ).encode("ascii")
    ).hexdigest()[:16]
    return _analysis_cache_root(project) / "scenes" / f"{fingerprint}-{settings_key}.json"


def _load_scene_cache(
    project: Project, fingerprint: str, config: VideoBuilderSettings
) -> tuple[SceneRange, ...] | None:
    path = _scene_cache_path(project, fingerprint, config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["scenes"]
    except (FileNotFoundError, OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCENE_CACHE_SCHEMA_VERSION
        or payload.get("footage_fingerprint") != fingerprint
        or not isinstance(rows, list)
        or not rows
    ):
        return None
    scenes: list[SceneRange] = []
    previous_end = 0.0
    try:
        for index, row in enumerate(rows):
            start = float(row["start"])
            end = float(row["end"])
            if start < 0 or end <= start or start + 0.01 < previous_end:
                return None
            scenes.append(SceneRange(index, start, end))
            previous_end = end
    except (KeyError, TypeError, ValueError):
        return None
    return tuple(scenes)


def _write_scene_cache(
    project: Project,
    fingerprint: str,
    config: VideoBuilderSettings,
    scenes: tuple[SceneRange, ...],
) -> None:
    _atomic_json(
        _scene_cache_path(project, fingerprint, config),
        {
            "schema_version": SCENE_CACHE_SCHEMA_VERSION,
            "footage_fingerprint": fingerprint,
            "scene_threshold": config.scene_threshold,
            "scene_min_seconds": config.scene_min_seconds,
            "scenes": [asdict(scene) for scene in scenes],
        },
    )


def _load_plan_cache(
    project: Project,
    beat: dict,
    sources: list[_Source],
    config: VideoBuilderSettings,
    semantics: dict[str, str],
    visual_model: str,
    history: list[tuple[Path, float, float]],
    cut_offset: int,
) -> tuple[list[_Cut], list[tuple[Path, float, float]]] | None:
    cache_key = _plan_cache_key(
        project, beat, sources, config, semantics, visual_model, history
    )
    path = _plan_cache_path(project, str(beat["code"]).upper(), cache_key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["cuts"]
        history_rows = payload["history"]
    except (FileNotFoundError, OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("cache_key") != cache_key
        or not isinstance(rows, list)
        or not isinstance(history_rows, list)
    ):
        return None
    try:
        cuts = [
            _cut_from_plan_cache(row, cut_offset + index)
            for index, row in enumerate(rows, start=1)
        ]
        cached_history = [
            (
                (project.root / str(row["path"])).resolve(),
                float(row["start"]),
                float(row["end"]),
            )
            for row in history_rows
            if isinstance(row, dict)
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return cuts, cached_history


def _write_plan_cache(
    project: Project,
    beat: dict,
    sources: list[_Source],
    config: VideoBuilderSettings,
    semantics: dict[str, str],
    visual_model: str,
    history_before: list[tuple[Path, float, float]],
    cuts: list[_Cut],
    history_added: list[tuple[Path, float, float]],
) -> None:
    cache_key = _plan_cache_key(
        project, beat, sources, config, semantics, visual_model, history_before
    )
    _atomic_json(
        _plan_cache_path(project, str(beat["code"]).upper(), cache_key),
        {
            "schema_version": 1,
            "cache_key": cache_key,
            "beat": str(beat["code"]).upper(),
            "cuts": [asdict(cut) for cut in cuts],
            "history": _history_signature(project, history_added),
        },
    )


def _plan_cache_path(project: Project, code: str, cache_key: str) -> Path:
    safe_code = re.sub(r"[^A-Z0-9_-]+", "-", code.upper()).strip("-") or "beat"
    return _analysis_cache_root(project) / "plans" / f"{safe_code}-{cache_key}.json"


def _plan_cache_key(
    project: Project,
    beat: dict,
    sources: list[_Source],
    config: VideoBuilderSettings,
    semantics: dict[str, str],
    visual_model: str,
    history: list[tuple[Path, float, float]],
) -> str:
    payload = {
        "beat": {
            "code": str(beat.get("code", "")).upper(),
            "start": round(float(beat.get("start_seconds", 0.0)), 6),
            "end": round(float(beat.get("end_seconds", 0.0)), 6),
            "narration": str(beat.get("narration", "")),
        },
        "settings": asdict(config),
        "semantics": semantics,
        "visual_model": visual_model,
        "sources": [
            {
                "path": source.path.relative_to(project.root).as_posix(),
                "fingerprint": source.fingerprint,
                "duration": round(source.duration, 6),
                "duration_verified": source.duration_verified,
                "width": source.width,
                "height": source.height,
                "technical_score": source.technical_score,
                "scenes": [
                    {
                        "index": scene.index,
                        "start": round(scene.start, 6),
                        "end": round(scene.end, 6),
                    }
                    for scene in source.scenes
                ],
            }
            for source in sources
        ],
        "history": _history_signature(project, history),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _history_signature(
    project: Project, history: list[tuple[Path, float, float]]
) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for path, start, end in history:
        try:
            relative = path.relative_to(project.root).as_posix()
        except ValueError:
            relative = path.as_posix()
        rows.append(
            {
                "path": relative,
                "start": round(float(start), 6),
                "end": round(float(end), 6),
            }
        )
    return rows


def _cut_from_plan_cache(row: dict, cut_number: int) -> _Cut:
    warnings = row.get("warnings", ())
    if isinstance(warnings, str):
        warnings = tuple(item.strip() for item in warnings.split("|") if item.strip())
    return _Cut(
        int(cut_number),
        str(row["beat"]),
        str(row.get("narration", "")),
        float(row["timeline_start"]),
        float(row["timeline_end"]),
        float(row["duration"]),
        str(row.get("footage", "")),
        float(row.get("source_start", 0.0)),
        float(row.get("source_end", 0.0)),
        float(row.get("technical_score", 0.0)),
        int(row.get("source_width", 0)),
        int(row.get("source_height", 0)),
        int(row.get("scene_index", -1)),
        (
            None
            if row.get("semantic_score") is None
            else float(row.get("semantic_score"))
        ),
        float(row.get("selection_score", 0.0)),
        tuple(str(item) for item in warnings),
    )


def _semantic_score(
    project: Project,
    scorer: SemanticScorer,
    text: str,
    option: _SceneOption,
) -> float:
    timestamp = (option.start + option.end) / 2.0
    cached = _load_semantic_cache(
        project,
        scorer.model_name,
        option.source.fingerprint,
        option.scene_index,
        option.start,
        option.end,
        text,
    )
    if cached is not None:
        return cached
    score = scorer.score(text, option.source.path, timestamp)
    _write_semantic_cache(
        project,
        scorer.model_name,
        option.source.fingerprint,
        option.scene_index,
        option.start,
        option.end,
        text,
        score,
    )
    return score


def _semantic_cache_path(
    project: Project,
    model_name: str,
    footage_fingerprint: str,
    scene_index: int,
    start: float,
    end: float,
    text: str,
) -> Path:
    payload = {
        "model": model_name,
        "footage_fingerprint": footage_fingerprint,
        "scene_index": scene_index,
        "start": round(start, 3),
        "end": round(end, 3),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    model_key = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:16]
    return _analysis_cache_root(project) / "semantic" / model_key / f"{key}.json"


def _load_semantic_cache(
    project: Project,
    model_name: str,
    footage_fingerprint: str,
    scene_index: int,
    start: float,
    end: float,
    text: str,
) -> float | None:
    path = _semantic_cache_path(
        project, model_name, footage_fingerprint, scene_index, start, end, text
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        score = float(payload["score"])
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("model") != model_name
        or payload.get("footage_fingerprint") != footage_fingerprint
        or int(payload.get("scene_index", -1)) != scene_index
        or str(payload.get("text_sha256", ""))
        != hashlib.sha256(text.encode("utf-8")).hexdigest()
        or not 0.0 <= score <= 1.0
    ):
        return None
    return round(score, 6)


def _write_semantic_cache(
    project: Project,
    model_name: str,
    footage_fingerprint: str,
    scene_index: int,
    start: float,
    end: float,
    text: str,
    score: float,
) -> None:
    if not footage_fingerprint:
        return
    bounded = round(max(0.0, min(1.0, float(score))), 6)
    _atomic_json(
        _semantic_cache_path(
            project, model_name, footage_fingerprint, scene_index, start, end, text
        ),
        {
            "schema_version": 1,
            "model": model_name,
            "footage_fingerprint": footage_fingerprint,
            "scene_index": scene_index,
            "start": round(start, 6),
            "end": round(end, 6),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "score": bounded,
        },
    )


def _load_beat_semantics(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    return {
        str(row.get("ma_beat", "")).upper(): {
            "main_idea": str(row.get("y_chinh", "")),
            "keywords": str(row.get("tu_khoa", "")),
            "desired_visual": str(row.get("hinh_can_tim", "")),
            "avoid": str(row.get("tranh", "")),
        }
        for row in rows
        if row.get("ma_beat")
    }


def _manifest_metadata(path: Path) -> dict[str, dict[str, float | int]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, dict[str, float | int]] = {}
    for item in payload.get("selections", []) if isinstance(payload, dict) else []:
        try:
            filename = str(item["filename"])
            duration = float(item["duration"])
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if filename and duration > 0:
            result[filename] = {
                "duration": duration,
                "width": width,
                "height": height,
            }
    return result


def _technical_score(
    duration_verified: bool,
    width: int,
    height: int,
    config: VideoBuilderSettings,
) -> float:
    target_width, target_height = (
        (1280, 720) if config.resolution == "720p" else (1920, 1080)
    )
    duration_score = 1.0 if duration_verified else 0.65
    resolution_score = (
        min(1.0, width / target_width, height / target_height)
        if width > 0 and height > 0
        else 0.0
    )
    orientation_score = 1.0 if width >= height and height > 0 else 0.0
    return round(
        0.45 * duration_score + 0.45 * resolution_score + 0.10 * orientation_score,
        6,
    )


def _filename_beat(path: Path, known: set[str]) -> str | None:
    stem = path.stem.upper()
    for code in sorted(known, key=len, reverse=True):
        if re.search(rf"(?:^|[^A-Z0-9]){re.escape(code)}(?=[^A-Z0-9]|$)", stem):
            return code
    return None


def _plan_beat(
    project: Project,
    beat: dict,
    sources: list[_Source],
    config: VideoBuilderSettings,
    cut_offset: int,
    semantics: dict[str, str],
    semantic_scorer: SemanticScorer | None,
    history: list[tuple[Path, float, float]],
) -> list[_Cut]:
    code = str(beat["code"]).upper()
    start = float(beat["start_seconds"])
    end = float(beat["end_seconds"])
    ranges = _cut_ranges(start, end, config)
    options = _scene_options(sources, config)
    if not options:
        return [
            _missing_cut(cut_offset + index, code, beat, cut_start, cut_end)
            for index, (cut_start, cut_end) in enumerate(ranges, start=1)
        ]

    positive_text = " · ".join(
        value
        for value in (
            semantics.get("desired_visual", ""),
            semantics.get("main_idea", ""),
            semantics.get("keywords", ""),
            str(beat.get("narration", "")),
        )
        if value
    )
    score_cache: dict[tuple[Path, int, str], float] = {}
    option_scores: list[float] = []
    semantic_scores: list[float | None] = []
    avoid_scores: list[float | None] = []
    for option in options:
        semantic: float | None = None
        avoid_score: float | None = None
        if semantic_scorer is not None:
            cache_key = (option.source.path, option.scene_index, positive_text)
            if cache_key not in score_cache:
                try:
                    score_cache[cache_key] = _semantic_score(
                        project,
                        semantic_scorer,
                        positive_text,
                        option,
                    )
                except VisualAnalysisError as exc:
                    raise VideoBuilderWorkflowError(str(exc)) from exc
            semantic = score_cache[cache_key]
            avoid_text = semantics.get("avoid", "").strip()
            if avoid_text:
                avoid_key = (option.source.path, option.scene_index, avoid_text)
                if avoid_key not in score_cache:
                    try:
                        score_cache[avoid_key] = _semantic_score(
                            project,
                            semantic_scorer,
                            avoid_text,
                            option,
                        )
                    except VisualAnalysisError as exc:
                        raise VideoBuilderWorkflowError(str(exc)) from exc
                avoid_score = score_cache[avoid_key]
                semantic = max(0.0, min(1.0, semantic - 0.25 * avoid_score))
        semantic_scores.append(semantic)
        avoid_scores.append(avoid_score)
        option_scores.append(
            round(
                0.65 * semantic + 0.35 * option.source.technical_score
                if semantic is not None
                else option.source.technical_score,
                6,
            )
        )

    beam: list[tuple[float, tuple[int, ...]]] = [(0.0, ())]
    beam_width = 96
    for cut_start, cut_end in ranges:
        required = cut_end - cut_start
        eligible = [
            index
            for index, option in enumerate(options)
            if option.end - option.start + 0.02 >= required
        ] or list(range(len(options)))
        eligible.sort(key=lambda index: option_scores[index], reverse=True)
        eligible = eligible[:48]
        next_beam: list[tuple[float, tuple[int, ...]]] = []
        for accumulated, selected in beam:
            prior = [*history, *(options[index].key for index in selected)]
            for option_index in eligible:
                penalty = _reuse_penalty(prior, options[option_index].key)
                next_beam.append(
                    (
                        accumulated + option_scores[option_index] - penalty,
                        (*selected, option_index),
                    )
                )
        next_beam.sort(key=lambda item: item[0], reverse=True)
        beam = next_beam[:beam_width]
    selected_indices = beam[0][1]

    rows: list[_Cut] = []
    for local_index, ((cut_start, cut_end), option_index) in enumerate(
        zip(ranges, selected_indices), start=1
    ):
        duration = cut_end - cut_start
        option = options[option_index]
        chosen = option.source
        source_start = option.start
        source_end = min(option.end, source_start + duration)
        warnings: list[str] = []
        if duration + 0.02 < config.min_cut_seconds:
            warnings.append("cut_shorter_than_minimum")
        if not chosen.duration_verified:
            warnings.append("duration_from_manifest_or_estimate")
        target_width, target_height = (
            (1280, 720) if config.resolution == "720p" else (1920, 1080)
        )
        if chosen.width and chosen.height and chosen.width < chosen.height:
            warnings.append("portrait_source")
        if (
            chosen.width
            and chosen.height
            and (chosen.width < target_width or chosen.height < target_height)
        ):
            warnings.append("source_below_target_resolution")
        if source_end - source_start + 0.02 < duration:
            warnings.append("source_shorter_than_cut")
        if avoid_scores[option_index] is not None and avoid_scores[option_index] >= 0.7:
            warnings.append("avoid_semantic_risk")
        if _reuse_penalty(history, option.key) >= 0.8:
            warnings.append("visual_region_reused")
        rows.append(
            _Cut(
                cut_offset + local_index,
                code,
                str(beat.get("narration", "")),
                round(cut_start, 6),
                round(cut_end, 6),
                round(duration, 6),
                chosen.path.relative_to(project.root).as_posix(),
                round(source_start, 6),
                round(source_end, 6),
                chosen.technical_score if chosen else 0.0,
                chosen.width if chosen else 0,
                chosen.height if chosen else 0,
                option.scene_index,
                semantic_scores[option_index],
                option_scores[option_index],
                tuple(warnings),
            )
        )
        history.append(option.key)
    return rows


def _scene_options(
    sources: list[_Source], config: VideoBuilderSettings
) -> list[_SceneOption]:
    options: list[_SceneOption] = []
    for source in sources:
        for scene in source.scenes or (SceneRange(0, 0.0, source.duration),):
            scene_duration = scene.end - scene.start
            window_count = max(1, math.ceil(scene_duration / config.max_cut_seconds))
            window = scene_duration / window_count
            for index in range(window_count):
                start = scene.start + index * window
                end = scene.end if index == window_count - 1 else start + window
                options.append(_SceneOption(source, scene.index, start, end))
    return options


def _reuse_penalty(
    history: list[tuple[Path, float, float]],
    current: tuple[Path, float, float],
) -> float:
    penalty = 0.0
    for distance, previous in enumerate(reversed(history[-18:]), start=1):
        if previous[0] != current[0]:
            continue
        overlap = max(0.0, min(previous[2], current[2]) - max(previous[1], current[1]))
        if overlap > 0:
            ratio = overlap / max(0.001, min(previous[2] - previous[1], current[2] - current[1]))
            penalty += (1.35 if distance == 1 else 0.9 / distance) * ratio
        elif current[1] < previous[1]:
            penalty += 0.12 / distance
        else:
            penalty += 0.02 / distance
    return penalty


def _missing_cut(
    cut: int, code: str, beat: dict, start: float, end: float
) -> _Cut:
    return _Cut(
        cut,
        code,
        str(beat.get("narration", "")),
        round(start, 6),
        round(end, 6),
        round(end - start, 6),
        "",
        0.0,
        0.0,
        0.0,
        0,
        0,
        -1,
        None,
        0.0,
        ("missing_footage",),
    )


def _cut_ranges(
    start: float, end: float, config: VideoBuilderSettings
) -> list[tuple[float, float]]:
    duration = end - start
    count = max(1, math.ceil(duration / config.max_cut_seconds))
    preferred = max(1, round(duration / config.target_cut_seconds))
    count = max(count, preferred)
    while count > 1 and duration / count < config.min_cut_seconds:
        count -= 1
    return [
        (
            start + duration * index / count,
            start + duration * (index + 1) / count,
        )
        for index in range(count)
    ]


def _input_fingerprint(project: Project, config: VideoBuilderSettings) -> str:
    payload = {
        "script": _sha256(project.path_for("tts_script")),
        "subtitle": _sha256(project.path_for("subtitle_file")),
        "beats": _sha256(project.path_for("beat_file")),
        "beat_timing": _sha256(project.path_for("beat_timing_file")),
        "footage_manifest": (
            _sha256(project.path_for("footage_manifest"))
            if project.path_for("footage_manifest").is_file()
            else ""
        ),
        "settings": asdict(config),
        "footage": [
            {
                "path": path.relative_to(project.root).as_posix(),
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(project.path_for("footage_dir").rglob("*"))
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_csv(path: Path, cuts: list[_Cut]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=TIMELINE_COLUMNS)
            writer.writeheader()
            writer.writerows(cut.csv_row() for cut in cuts)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_csv_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=TIMELINE_COLUMNS)
            writer.writeheader()
            for source in rows:
                row = {column: source.get(column, "") for column in TIMELINE_COLUMNS}
                warnings = row.get("warnings", "")
                if isinstance(warnings, (list, tuple)):
                    row["warnings"] = " | ".join(str(item) for item in warnings)
                writer.writerow(row)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_outputs(previous: dict[Path, bytes | None]) -> None:
    for path, content in previous.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_bytes(path, content)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
