from __future__ import annotations

import copy
import csv
import json
import re
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, afx

from ..audio_mix import load_configured_music_rows
from ..config import PipelineConfig
from ..inputs import discover_voice_files, open_voice_timeline
from ..output import (
    load_render_plan,
    render_video,
)
from .media_exporter import export_capcut_scenes
from .models import CapCutPackage
from .draft_adapter import create_capcut_draft
from .subtitle_exporter import (
    captions_from_timeline,
    captions_from_word_timings,
    write_srt,
)


PACKAGE_SCHEMA_VERSION = 2
_DURATION_TOLERANCE_SECONDS = 0.75


def _load_report(config: PipelineConfig) -> dict:
    if not config.report_file.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy Report phân tích: {config.report_file}. "
            "Hãy chạy Phân tích trước khi xuất sang CapCut."
        )
    report = json.loads(config.report_file.read_text(encoding="utf-8-sig"))
    rows = report.get("timeline")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Report phân tích không hợp lệ: {config.report_file}")
    return report


def _section_source_report(
    config: PipelineConfig,
    full_report: dict | None,
    section_index: int,
) -> dict:
    preview = (
        config.cache_dir
        / "section_previews"
        / f"{section_index:03d}.json"
    )
    preview_paths = [preview]
    preview_dir = preview.parent
    if preview_dir.is_dir():
        preview_paths.extend(
            path for path in preview_dir.glob("*.json") if path != preview
        )
    for preview_path in preview_paths:
        if not preview_path.is_file():
            continue
        report = json.loads(
            preview_path.read_text(encoding="utf-8-sig")
        )
        if (
            report.get("analysis_scope") == "section_preview"
            and any(
                int(item.get("index", 0)) == section_index
                for item in report.get("sections", [])
            )
        ):
            return report
    if full_report is not None and any(
        int(row.get("section_index", 0)) == section_index
        for row in full_report.get("timeline", [])
    ):
        return full_report
    raise ValueError(
        f"Section {section_index} chưa có kết quả phân tích để xuất CapCut."
    )


def load_section_report(
    config: PipelineConfig,
    section_indexes: set[int],
) -> dict:
    full_report = (
        _load_report(config) if config.report_file.is_file() else None
    )
    ordered = sorted(section_indexes)
    merged = None
    timeline = []
    sections = []
    words = []
    audio = []
    voice_timeline = []
    cursor = 0.0
    for section_index in ordered:
        source = _section_source_report(
            config, full_report, section_index
        )
        source_sections = {
            int(item["index"]): item
            for item in source.get("sections", [])
        }
        section = source_sections.get(section_index)
        if section is None:
            raise ValueError(
                f"Report Section {section_index} thiếu metadata Audio."
            )
        if merged is None:
            merged = copy.deepcopy(source)
        old_start = float(section["timeline_start"])
        old_end = float(section["timeline_end"])
        duration = float(section["duration"])
        shift = cursor - old_start

        section_copy = copy.deepcopy(section)
        section_copy["timeline_start"] = round(cursor, 6)
        section_copy["timeline_end"] = round(cursor + duration, 6)
        sections.append(section_copy)
        audio_path = str(section["audio"])
        audio.append(audio_path)
        voice_timeline.append(
            {
                "name": Path(audio_path).name,
                "start": round(cursor, 6),
                "end": round(cursor + duration, 6),
                "duration": round(duration, 6),
                "srt": section.get("srt"),
            }
        )
        for row in source.get("timeline", []):
            if int(row.get("section_index", 0)) != section_index:
                continue
            item = copy.deepcopy(row)
            for key in (
                "timeline_start", "timeline_end",
                "visual_start", "visual_end",
            ):
                if key in item:
                    item[key] = round(float(item[key]) + shift, 6)
            timeline.append(item)
        for word in source.get("word_timings", []):
            start = float(word["start"])
            end = float(word["end"])
            if start < old_end and end > old_start:
                item = copy.deepcopy(word)
                item["start"] = round(start + shift, 6)
                item["end"] = round(end + shift, 6)
                words.append(item)
        cursor += duration
    if merged is None or not timeline:
        raise ValueError("Không có Section hợp lệ để xuất CapCut.")
    merged["analysis_scope"] = "section_export"
    merged["timeline"] = timeline
    merged["sections"] = sections
    merged["word_timings"] = words
    merged["inputs"]["audio"] = audio
    merged["inputs"]["voice_timeline"] = voice_timeline
    return merged


def _voice_paths(report: dict) -> list[Path]:
    values = report.get("inputs", {}).get("audio", [])
    paths = [Path(str(value)) for value in values]
    if not paths:
        raise ValueError("Report không chứa danh sách Voice Audio")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Không tìm thấy Voice Audio dùng bởi Report: "
            + ", ".join(missing)
        )
    return paths


def _paths_match(left: list[Path], right: list[Path]) -> bool:
    if len(left) != len(right):
        return False
    return all(
        str(left_path.resolve()).lower() == str(right_path.resolve()).lower()
        for left_path, right_path in zip(left, right)
    )


def _report_audio_duration(report: dict) -> float:
    voices = report.get("inputs", {}).get("voice_timeline", [])
    if isinstance(voices, list) and voices:
        return max(float(item.get("end", 0.0)) for item in voices)
    sections = report.get("sections", [])
    if isinstance(sections, list) and sections:
        return max(float(item.get("timeline_end", 0.0)) for item in sections)
    return max(
        float(row.get("timeline_end", 0.0))
        for row in report.get("timeline", [])
    )


def _timeline_duration(report: dict) -> float:
    return max(
        float(row.get("timeline_end", 0.0))
        for row in report["timeline"]
    )


def _validate_report_matches_current_audio(
    config: PipelineConfig,
    report: dict,
) -> None:
    report_paths = _voice_paths(report)
    current_paths = discover_voice_files(config)
    if not _paths_match(report_paths, current_paths):
        raise ValueError(
            "Report phan tich khong khop Audio hien tai. "
            "Hay bam Phan tich lai truoc khi xuat CapCut. "
            "Report dung: "
            + ", ".join(str(path) for path in report_paths)
            + "; hien tai: "
            + ", ".join(str(path) for path in current_paths)
        )
    audio_clip, source_clips, _ = open_voice_timeline(current_paths)
    try:
        actual_duration = float(audio_clip.duration)
    finally:
        if len(source_clips) > 1:
            audio_clip.close()
        for clip in source_clips:
            clip.close()
    report_duration = _report_audio_duration(report)
    if abs(actual_duration - report_duration) > _DURATION_TOLERANCE_SECONDS:
        raise ValueError(
            "Report phan tich da cu so voi Audio hien tai. "
            f"Report: {report_duration / 60.0:.2f} phut; "
            f"Audio hien tai: {actual_duration / 60.0:.2f} phut. "
            "Hay bam Phan tich lai tu dau roi xuat CapCut lai."
        )
    timeline_duration = _timeline_duration(report)
    if timeline_duration + _DURATION_TOLERANCE_SECONDS < report_duration:
        raise ValueError(
            "Report phan tich chua phu het Audio. "
            f"Timeline: {timeline_duration / 60.0:.2f} phut; "
            f"Audio: {report_duration / 60.0:.2f} phut. "
            "Hay bam Phan tich lai tu dau roi xuat CapCut lai."
        )


def _read_scene_manifest(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_package_manifest(
    path: Path,
    *,
    config: PipelineConfig,
    report: dict,
    scene_rows: list[dict],
    audio_section_rows: list[dict],
    background_music_rows: list[dict],
    reference_video: Path | None,
    captions_enabled: bool,
    caption_max_lines: int,
    caption_max_characters_per_line: int,
    narration_duration: float,
) -> None:
    timeline_rows = report["timeline"]
    if len(scene_rows) != len(timeline_rows):
        raise ValueError(
            "Số Scene đã xuất không khớp với Timeline phân tích"
        )
    scenes = []
    for exported, timeline in zip(scene_rows, timeline_rows):
        scenes.append(
            {
                "order": int(exported["order"]),
                "file": f"scenes/{exported['scene_file']}",
                "beats": timeline.get("beats", []),
                "timeline_start": float(timeline.get("timeline_start", 0)),
                "timeline_end": float(timeline.get("timeline_end", 0)),
                "duration": float(exported["duration"]),
                "source_file": str(timeline.get("footage", "")),
                "source_start": float(exported["source_start"]),
                "source_end": float(exported["source_end"]),
                "narration": str(timeline.get("narration", "")),
            }
        )
    timeline_duration = _timeline_duration(report)
    duration = max(timeline_duration, float(narration_duration))
    payload = {
        "schema": "footage-video-builder.capcut-package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "project": config.base_dir.name,
        "canvas": {
            "width": config.resolution[0],
            "height": config.resolution[1],
            "fps": config.output_fps,
            "duration": round(duration, 6),
            "timeline_duration": round(timeline_duration, 6),
            "narration_duration": round(float(narration_duration), 6),
        },
        "tracks": {
            "video": scenes,
            "narration": {
                "file": "narration.wav",
                "timeline_start": 0.0,
            },
            "audio_sections": audio_section_rows,
            "background_music": background_music_rows,
            "captions": {
                "file": "captions.srt",
                "format": "srt",
                "encoding": "utf-8",
                "enabled": captions_enabled,
                "max_lines": caption_max_lines,
                "max_characters_per_line": (
                    caption_max_characters_per_line
                ),
            },
            "reference_video": (
                reference_video.name if reference_video is not None else None
            ),
        },
        "capcut_workflow": {
            "media_mode": "individual_scenes",
            "draft_adapter": "not_configured",
            "instructions": [
                "Import toàn bộ file trong scenes theo thứ tự tên file.",
                "Đặt narration.wav tại 00:00:00 và giữ nguyên toàn bộ Audio.",
                "Import captions.srt trong Captions > Add Captions.",
                "Áp hiệu ứng, transition và caption style trong CapCut.",
                "Dùng reference.mp4 để đối chiếu timeline nếu cần.",
            ],
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_media_name(index: int, role: str, source: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")
    if not stem:
        stem = role
    return f"{index:03d}_{role}_{stem}{source.suffix.lower()}"


def _audio_duration(path: Path) -> float:
    clip = AudioFileClip(str(path))
    try:
        duration = float(clip.duration or 0.0)
    finally:
        clip.close()
    if duration <= 0:
        raise ValueError(f"File nhac nen khong co duration hop le: {path}")
    return duration


def _db_to_volume(db: float) -> float:
    return 10 ** (db / 20.0)


def _append_music_segments(
    rows: list[dict],
    *,
    file_value: str,
    role: str,
    name: str,
    music_duration: float,
    start: float,
    end: float,
    repeat: bool,
    volume: float,
) -> float:
    cursor = start
    while cursor < end:
        remaining = end - cursor
        segment_duration = min(music_duration, remaining)
        if segment_duration <= 0:
            break
        rows.append(
            {
                "file": file_value,
                "role": role,
                "name": name,
                "timeline_start": round(cursor, 6),
                "duration": round(segment_duration, 6),
                "source_start": 0.0,
                "source_duration": round(segment_duration, 6),
                "volume": volume,
                "repeat": bool(repeat),
            }
        )
        cursor += segment_duration
        if not repeat:
            break
    return cursor


def _export_cue_sheet_background_music(
    output_dir: Path,
    cue_rows: list[dict],
    total_duration: float,
) -> list[dict]:
    music_dir = output_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    destination = music_dir / "background_music.wav"
    music_clips = []
    opened_sources = []
    try:
        for row in cue_rows:
            source_path = Path(str(row["path"])).resolve()
            if not source_path.is_file():
                raise FileNotFoundError(
                    f"Khong tim thay file nhac nen: {source_path}"
                )
            source = AudioFileClip(str(source_path))
            opened_sources.append(source)
            source_start = float(row.get("source_start", 0.0))
            duration = min(
                float(row["duration"]),
                max(0.0, float(source.duration) - source_start),
            )
            if duration <= 0:
                raise ValueError(
                    f"Cue nhac vuot ngoai thoi luong file: {source_path}"
                )
            clip = source.subclipped(source_start, source_start + duration)
            clip = clip.with_volume_scaled(float(row.get("volume", 1.0)))
            effects = []
            fade_in = min(float(row.get("fade_in", 0.0)), duration)
            fade_out = min(float(row.get("fade_out", 0.0)), duration)
            if fade_in > 0:
                effects.append(afx.AudioFadeIn(fade_in))
            if fade_out > 0:
                effects.append(afx.AudioFadeOut(fade_out))
            if effects:
                clip = clip.with_effects(effects)
            music_clips.append(clip.with_start(float(row["timeline_start"])))
        composite = CompositeAudioClip(music_clips).with_duration(total_duration)
        try:
            composite.write_audiofile(
                str(destination),
                fps=48_000,
                codec="pcm_s16le",
                logger=None,
            )
        finally:
            composite.close()
    finally:
        for clip in music_clips:
            clip.close()
        for source in opened_sources:
            source.close()
    return [
        {
            "cue": "DWG_BACKGROUND_MUSIC",
            "file": f"music/{destination.name}",
            "name": destination.name,
            "role": "dwg_cue_mix",
            "timeline_start": 0.0,
            "duration": round(total_duration, 6),
            "source_start": 0.0,
            "source_duration": round(total_duration, 6),
            "gain_db": 0.0,
            "volume": 1.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "target_music_lufs": None,
            "notes": "Cue sheet rendered to one baked background music file",
            "cue_count": len(cue_rows),
            "fades_baked_into_file": True,
            "gain_baked_into_file": True,
        }
    ]


def _export_background_music(
    output_dir: Path,
    report: dict,
    *,
    hook_music: Path | None,
    body_music: list[dict] | None,
    hook_volume_db: float = -17.0,
    cue_rows: list[dict] | None = None,
    total_duration: float | None = None,
) -> list[dict]:
    total_duration = (
        float(total_duration)
        if total_duration is not None
        else _timeline_duration(report)
    )
    requested = []
    if hook_music is not None:
        requested.append(("hook", hook_music, False))
    for row in body_music or []:
        requested.append(
            ("body", Path(str(row["path"])), bool(row.get("repeat", False)))
        )
    if cue_rows and hook_music is None and not body_music:
        return _export_cue_sheet_background_music(
            output_dir, cue_rows, total_duration
        )
    if not requested:
        return []
    for _role, source, _repeat in requested:
        if not source.is_file():
            raise FileNotFoundError(f"Khong tim thay file nhac nen: {source}")
    music_dir = output_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    exported_files: dict[Path, str] = {}
    for index, (role, source, _repeat) in enumerate(requested, start=1):
        resolved = source.resolve()
        if resolved in exported_files:
            continue
        destination = music_dir / _safe_media_name(index, role, resolved)
        shutil.copy2(resolved, destination)
        exported_files[resolved] = f"music/{destination.name}"

    rows: list[dict] = []
    cursor = 0.0
    if hook_music is not None:
        source = hook_music.resolve()
        cursor = _append_music_segments(
            rows,
            file_value=exported_files[source],
            role="hook",
            name=source.name,
            music_duration=_audio_duration(source),
            start=0.0,
            end=total_duration,
            repeat=False,
            volume=_db_to_volume(hook_volume_db),
        )
    for row in body_music or []:
        if cursor >= total_duration:
            break
        source = Path(str(row["path"])).resolve()
        repeat = bool(row.get("repeat", False))
        body_volume_db = float(row.get("volume_db", -20.0))
        cursor = _append_music_segments(
            rows,
            file_value=exported_files[source],
            role="body",
            name=source.name,
            music_duration=_audio_duration(source),
            start=cursor,
            end=total_duration,
            repeat=repeat,
            volume=_db_to_volume(body_volume_db),
        )
        if repeat:
            break
    return rows


def _export_section_audio(
    report: dict,
    output_dir: Path,
) -> list[dict]:
    sections = report.get("sections", [])
    if not sections:
        return []
    audio_dir = output_dir / "audio_sections"
    audio_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for section in sections:
        source = Path(str(section["audio"]))
        if not source.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy Audio của Section: {source}"
            )
        safe_name = re.sub(
            r"[^A-Za-z0-9_-]+",
            "-",
            str(section.get("name", "")),
        ).strip("-") or "UNTITLED"
        filename = (
            f"{int(section['index']):03d}_{safe_name}"
            f"{source.suffix.lower()}"
        )
        destination = audio_dir / filename
        shutil.copy2(source, destination)
        rows.append(
            {
                "section_index": int(section["index"]),
                "section_name": str(section.get("name", "")),
                "file": f"audio_sections/{filename}",
                "timeline_start": float(section["timeline_start"]),
                "timeline_end": float(section["timeline_end"]),
                "duration": float(section["duration"]),
            }
        )
    return rows


def build_capcut_package(
    config: PipelineConfig,
    output_dir: Path,
    *,
    include_reference_video: bool = True,
    template_dir: Path | None = None,
    draft_name: str | None = None,
    drafts_root: Path | None = None,
    register_draft: bool = True,
    section_indexes: set[int] | None = None,
    replace_draft: bool = False,
    hook_music: Path | None = None,
    hook_volume_db: float = -17.0,
    body_music: list[dict] | None = None,
    caption_max_lines: int = 4,
    caption_max_characters_per_line: int = 14,
) -> CapCutPackage:
    pending_draft_install = output_dir / ".capcut_draft_install_pending.json"
    manifest_file = output_dir / "capcut_manifest.json"
    if template_dir is not None and pending_draft_install.is_file():
        try:
            pending = json.loads(
                pending_draft_install.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            pending = {}
        required_files = [manifest_file, output_dir / "narration.wav"]
        existing_manifest = {}
        if manifest_file.is_file():
            try:
                existing_manifest = json.loads(
                    manifest_file.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing_manifest = {}
        caption_profile = (
            existing_manifest.get("tracks", {}).get("captions", {})
        )
        profile_matches = (
            caption_profile.get("max_lines") == caption_max_lines
            and caption_profile.get("max_characters_per_line")
            == caption_max_characters_per_line
        )
        current_audio_matches = False
        try:
            retry_report = _load_report(config)
            _validate_report_matches_current_audio(config, retry_report)
            current_audio_duration = _report_audio_duration(retry_report)
            current_audio_matches = (
                abs(
                    float(
                        existing_manifest.get("canvas", {}).get(
                            "narration_duration", -1.0
                        )
                    )
                    - current_audio_duration
                )
                <= _DURATION_TOLERANCE_SECONDS
            )
        except (OSError, ValueError, TypeError, KeyError):
            current_audio_matches = False
        if (
            all(path.is_file() for path in required_files)
            and profile_matches
            and current_audio_matches
        ):
            retry_template = Path(
                str(pending.get("template_dir") or template_dir)
            ).resolve()
            retry_drafts_root = pending.get("drafts_root")
            retry_root = (
                Path(str(retry_drafts_root)).resolve()
                if retry_drafts_root
                else (drafts_root or retry_template.parent).resolve()
            )
            retry_name = str(
                pending.get("draft_name")
                or draft_name
                or config.base_dir.name
            )
            retry_target = retry_root / retry_name
            retry_replace = bool(
                pending.get("replace_existing", replace_draft)
                or (
                    retry_target
                    / "Resources"
                    / "CapCutAdapter"
                ).is_dir()
                or (
                    retry_root
                    / f".{retry_name}.capcut_adapter_backup"
                ).is_dir()
            )
            print(
                "Phát hiện gói CapCut đã xuất xong từ lần chạy trước; "
                "chỉ thử lại bước cài Draft."
            )
            create_capcut_draft(
                output_dir,
                retry_template,
                retry_name,
                drafts_root=retry_root,
                register=bool(pending.get("register", register_draft)),
                replace_existing=retry_replace,
            )
            pending_draft_install.unlink(missing_ok=True)
            manifest = existing_manifest
            reference_path = output_dir / "reference.mp4"
            return CapCutPackage(
                root=output_dir,
                scenes_dir=output_dir / "scenes",
                narration_file=output_dir / "narration.wav",
                captions_file=output_dir / "captions.srt",
                manifest_file=manifest_file,
                reference_video=(
                    reference_path
                    if manifest.get("tracks", {}).get("reference_video")
                    and reference_path.is_file()
                    else None
                ),
            )
    report = (
        load_section_report(config, section_indexes)
        if section_indexes
        else _load_report(config)
    )
    _validate_report_matches_current_audio(config, report)
    voice_paths = _voice_paths(report)
    audio_clip, source_clips, _ = open_voice_timeline(voice_paths)
    narration_duration = float(audio_clip.duration)
    timeline_duration = _timeline_duration(report)
    total_duration = max(timeline_duration, narration_duration)
    output_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir = output_dir / "scenes"
    scene_manifest = export_capcut_scenes(
        config, report["timeline"], scenes_dir
    )
    scene_rows = _read_scene_manifest(scene_manifest)
    # The product now has one complete narration file. CapCut consumes the
    # generated narration.wav directly instead of creating per-section audio.
    audio_section_rows: list[dict] = []
    background_music_rows = _export_background_music(
        output_dir,
        report,
        hook_music=hook_music,
        hook_volume_db=hook_volume_db,
        body_music=body_music,
        cue_rows=(
            load_configured_music_rows(
                config,
                total_duration,
            )
            if hook_music is None and not body_music
            else None
        ),
        total_duration=total_duration,
    )

    timings = report.get("word_timings")
    cues = (
        captions_from_word_timings(
            timings,
            max_lines=caption_max_lines,
            max_characters_per_line=caption_max_characters_per_line,
        )
        if isinstance(timings, list) and timings
        else captions_from_timeline(
            report["timeline"],
            max_lines=caption_max_lines,
            max_characters_per_line=caption_max_characters_per_line,
        )
    )
    captions_file = write_srt(output_dir / "captions.srt", cues)

    narration_file = output_dir / "narration.wav"
    reference_video = (
        output_dir / "reference.mp4"
        if include_reference_video
        else None
    )
    stale_reference = output_dir / "reference.mp4"
    if reference_video is None and stale_reference.is_file():
        stale_reference.unlink()
    try:
        print(f"Đang xuất Audio CapCut: {narration_file.name}")
        audio_clip.write_audiofile(
            str(narration_file),
            fps=48_000,
            codec="pcm_s16le",
            logger=None,
        )
        if reference_video is not None:
            print("Đang tạo MP4 tham chiếu cho CapCut...")
            selected_report = output_dir / ".selected_report.json"
            selected_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            reference_config = replace(
                config,
                output_file=reference_video,
                report_file=selected_report,
                enable_background_music=(
                    config.enable_background_music
                    and hook_music is None
                    and not body_music
                ),
            )
            try:
                segments, selected = load_render_plan(reference_config)
                render_video(
                    reference_config, segments, selected, audio_clip
                )
            finally:
                selected_report.unlink(missing_ok=True)
    finally:
        if len(source_clips) > 1:
            audio_clip.close()
        for clip in source_clips:
            clip.close()

    _write_package_manifest(
        manifest_file,
        config=config,
        report=report,
        scene_rows=scene_rows,
        audio_section_rows=audio_section_rows,
        background_music_rows=background_music_rows,
        reference_video=reference_video,
        captions_enabled=bool(cues),
        caption_max_lines=caption_max_lines,
        caption_max_characters_per_line=(
            caption_max_characters_per_line
        ),
        narration_duration=narration_duration,
    )
    readme = output_dir / "README_CAPCUT.txt"
    reference_step = (
        "5. Dùng reference.mp4 để kiểm tra thứ tự và nhịp dựng.\n"
        if reference_video is not None
        else ""
    )
    readme.write_text(
        "GÓI DỰNG CAPCUT\n\n"
        "1. Import các file trong thư mục scenes theo thứ tự tên.\n"
        "2. Đặt narration.wav tại 00:00:00; không cắt hoặc chia nhỏ Audio.\n"
        "3. Import captions.srt qua Captions > Add Captions.\n"
        "4. Thêm transition, hiệu ứng và áp caption style trong CapCut.\n"
        f"{reference_step}\n"
        "capcut_manifest.json chứa vị trí timeline chính xác cho Draft Adapter "
        "ở giai đoạn sau.\n",
        encoding="utf-8",
    )
    print(f"Gói CapCut đã sẵn sàng: {output_dir}")
    print(f"CapCut manifest: {manifest_file}")
    if template_dir is not None:
        pending_draft_install.write_text(
            json.dumps(
                {
                    "draft_name": draft_name or config.base_dir.name,
                    "template_dir": str(template_dir.resolve()),
                    "drafts_root": (
                        str(drafts_root.resolve())
                        if drafts_root is not None
                        else None
                    ),
                    "register": register_draft,
                    "replace_existing": replace_draft,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        create_capcut_draft(
            output_dir,
            template_dir,
            draft_name or config.base_dir.name,
            drafts_root=drafts_root,
            register=register_draft,
            replace_existing=replace_draft,
        )
        pending_draft_install.unlink(missing_ok=True)
    return CapCutPackage(
        root=output_dir,
        scenes_dir=scenes_dir,
        narration_file=narration_file,
        captions_file=captions_file,
        manifest_file=manifest_file,
        reference_video=reference_video,
    )
