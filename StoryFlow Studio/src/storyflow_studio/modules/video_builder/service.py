"""Draft timeline analysis reusing validated Beat and Footage artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from ...core.media import probe_audio_duration
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
SemanticScorerFactory = Callable[[str, Path, bool], SemanticScorer | None]


class VideoBuilderService:
    """Analyze, review, override and render the canonical video timeline."""

    def __init__(
        self,
        duration_probe: DurationProbe = probe_audio_duration,
        scene_detector: SceneDetector | None = None,
        semantic_scorer_factory: SemanticScorerFactory = build_semantic_scorer,
        renderer: FFmpegTimelineRenderer | None = None,
        capcut_exporter: CapCutPackageExporter | None = None,
    ) -> None:
        self.duration_probe = duration_probe
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
            self.scene_detector,
            config,
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
            cuts.extend(
                _plan_beat(
                    project,
                    beat,
                    inventory.get(str(beat["code"]).upper(), []),
                    config,
                    len(cuts),
                    semantics.get(str(beat["code"]).upper(), {}),
                    semantic_scorer,
                    history,
                )
            )
            percent = 25 + int(55 * position / max(1, len(beats)))
            progress(
                VideoBuilderProgress(
                    "video_plan",
                    "running",
                    percent,
                    f"Planned {beat['code']} · {position}/{len(beats)} beats",
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
    scene_detector: SceneDetector,
    config: VideoBuilderSettings,
) -> dict[str, list[_Source]]:
    known = {str(beat["code"]).upper() for beat in beats}
    metadata = _manifest_metadata(project.path_for("footage_manifest"))
    result = {code: [] for code in known}
    directory = project.path_for("footage_dir")
    if not directory.is_dir():
        return result
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        code = _filename_beat(path, known)
        if code is None:
            continue
        probed = duration_probe(path)
        item = metadata.get(path.name, {})
        manifest_duration = item.get("duration")
        duration = probed or manifest_duration or config.max_cut_seconds
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        try:
            scenes = scene_detector.detect(
                path,
                max(0.1, float(duration)),
                config.scene_threshold,
                config.scene_min_seconds,
            )
        except (OSError, ValueError, VisualAnalysisError):
            scenes = (SceneRange(0, 0.0, max(0.1, float(duration))),)
        result[code].append(
            _Source(
                path,
                max(0.1, float(duration)),
                probed is not None,
                width,
                height,
                _technical_score(probed is not None, width, height, config),
                scenes,
            )
        )
    return result


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
                    score_cache[cache_key] = semantic_scorer.score(
                        positive_text,
                        option.source.path,
                        (option.start + option.end) / 2.0,
                    )
                except VisualAnalysisError as exc:
                    raise VideoBuilderWorkflowError(str(exc)) from exc
            semantic = score_cache[cache_key]
            avoid_text = semantics.get("avoid", "").strip()
            if avoid_text:
                avoid_key = (option.source.path, option.scene_index, avoid_text)
                if avoid_key not in score_cache:
                    try:
                        score_cache[avoid_key] = semantic_scorer.score(
                            avoid_text,
                            option.source.path,
                            (option.start + option.end) / 2.0,
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
