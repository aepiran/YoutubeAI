from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from ..subprocess_utils import hidden_subprocess_kwargs
from .subtitle_exporter import parse_srt


CAPCUT_TIMEBASE = 1_000_000
SUPPORTED_TEMPLATE_VERSION = 360000
SUPPORTED_APP_VERSION = "9.1.0"


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _capcut_path(path: Path) -> str:
    return path.resolve().as_posix()


def _microseconds(seconds: float) -> int:
    return max(1, round(seconds * CAPCUT_TIMEBASE))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _assert_capcut_closed() -> None:
    if os.name != "nt":
        return
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **hidden_subprocess_kwargs(),
    )
    if "CapCut.exe" in completed.stdout:
        raise RuntimeError(
            "Hãy đóng CapCut trước khi tạo Draft để tránh CapCut ghi đè "
            "root_meta_info.json."
        )


def _find_material(content: dict, material_id: str) -> tuple[str, dict]:
    for collection, values in content["materials"].items():
        for material in values or []:
            if material.get("id") == material_id:
                return collection, material
    raise ValueError(f"Template thiếu Material tham chiếu: {material_id}")


def _set_caption_text(material: dict, text: str) -> None:
    payload = json.loads(material["content"])
    payload["text"] = text
    for style in payload.get("styles", []):
        style["range"] = [0, len(text)]
    material["content"] = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )


def _replace_video_track(
    content: dict,
    package_dir: Path,
    scene_rows: list[dict],
) -> None:
    video_track = next(
        track for track in content["tracks"] if track["type"] == "video"
    )
    template_segments = video_track["segments"]
    if not template_segments:
        raise ValueError("Template CapCut chưa có Video placeholder")
    template_videos = {}
    ref_sources = {}
    for template_segment in template_segments:
        material_id = template_segment["material_id"]
        if material_id not in template_videos:
            _, template_video = _find_material(content, material_id)
            template_videos[material_id] = template_video
        for ref_id in template_segment.get("extra_material_refs", []):
            if ref_id not in ref_sources:
                collection, material = _find_material(content, ref_id)
                ref_sources[ref_id] = (collection, material)

    video_ref_ids = set(ref_sources)
    for collection in {value[0] for value in ref_sources.values()}:
        content["materials"][collection] = [
            item
            for item in content["materials"][collection]
            if item.get("id") not in video_ref_ids
        ]

    videos = []
    segments = []
    for scene_index, row in enumerate(scene_rows):
        template_segment = template_segments[
            scene_index % len(template_segments)
        ]
        template_video = template_videos[
            template_segment["material_id"]
        ]
        scene_file = (package_dir / row["file"]).resolve()
        if not scene_file.is_file():
            raise FileNotFoundError(f"Không tìm thấy Scene: {scene_file}")
        start = _microseconds(float(row["timeline_start"]))
        if float(row["timeline_start"]) == 0:
            start = 0
        duration = _microseconds(float(row["duration"]))
        video = copy.deepcopy(template_video)
        video["id"] = _uuid()
        video["path"] = _capcut_path(scene_file)
        video["duration"] = duration
        video["material_name"] = scene_file.name
        video["name"] = scene_file.name
        video["width"] = 1920
        video["height"] = 1080
        videos.append(video)

        segment = copy.deepcopy(template_segment)
        segment["id"] = _uuid()
        segment["material_id"] = video["id"]
        segment["source_timerange"] = {"start": 0, "duration": duration}
        segment["target_timerange"] = {
            "start": start,
            "duration": duration,
        }
        new_refs = []
        for old_ref in template_segment.get("extra_material_refs", []):
            collection, source = ref_sources[old_ref]
            cloned = copy.deepcopy(source)
            cloned["id"] = _uuid()
            content["materials"][collection].append(cloned)
            new_refs.append(cloned["id"])
        segment["extra_material_refs"] = new_refs
        segments.append(segment)

    content["materials"]["videos"] = videos
    video_track["segments"] = segments


def _replace_audio_track(
    content: dict,
    package_dir: Path,
    audio_rows: list[dict],
    total_duration: int,
) -> None:
    audio_tracks = [
        track for track in content["tracks"] if track["type"] == "audio"
    ]
    if not audio_tracks:
        raise ValueError("Template CapCut chua co audio placeholder")
    audio_track = audio_tracks[0]
    if len(audio_track["segments"]) != 1:
        raise ValueError("Template CapCut phải có đúng một narration placeholder")
    template_segment = audio_track["segments"][0]
    _, template_audio = _find_material(
        content, template_segment["material_id"]
    )
    ref_sources = {}
    for ref_id in template_segment.get("extra_material_refs", []):
        collection, material = _find_material(content, ref_id)
        ref_sources[ref_id] = (collection, material)
    audio_ref_ids = set(ref_sources)
    for collection in {value[0] for value in ref_sources.values()}:
        content["materials"][collection] = [
            item
            for item in content["materials"][collection]
            if item.get("id") not in audio_ref_ids
        ]
    old_audio_ids = {
        segment.get("material_id")
        for track in audio_tracks
        for segment in track.get("segments", [])
    }

    if not audio_rows:
        audio_rows = [
            {
                "file": "narration.wav",
                "timeline_start": 0.0,
                "duration": total_duration / CAPCUT_TIMEBASE,
            }
        ]
    audios = []
    segments = []
    for row in audio_rows:
        audio_file = (package_dir / row["file"]).resolve()
        if not audio_file.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy Audio narration: {audio_file}"
            )
        duration = _microseconds(float(row["duration"]))
        start_value = float(row.get("timeline_start", 0.0))
        start = _microseconds(start_value) if start_value > 0 else 0
        audio = copy.deepcopy(template_audio)
        audio["id"] = _uuid()
        audio["path"] = _capcut_path(audio_file)
        audio["duration"] = duration
        audio["name"] = audio_file.name
        audio["material_name"] = audio_file.name
        audios.append(audio)

        segment = copy.deepcopy(template_segment)
        segment["id"] = _uuid()
        segment["material_id"] = audio["id"]
        segment["source_timerange"] = {"start": 0, "duration": duration}
        segment["target_timerange"] = {
            "start": start,
            "duration": duration,
        }
        new_refs = []
        for old_ref in template_segment.get("extra_material_refs", []):
            collection, source = ref_sources[old_ref]
            cloned = copy.deepcopy(source)
            cloned["id"] = _uuid()
            content["materials"][collection].append(cloned)
            new_refs.append(cloned["id"])
        segment["extra_material_refs"] = new_refs
        segments.append(segment)
    content["materials"]["audios"] = [
        item
        for item in content["materials"].get("audios", [])
        if item.get("id") not in old_audio_ids
    ] + audios
    audio_track["segments"] = segments
    content["tracks"] = [
        track
        for track in content["tracks"]
        if track["type"] != "audio" or track is audio_track
    ]


def _add_background_music_track(
    content: dict,
    package_dir: Path,
    music_rows: list[dict],
) -> None:
    if not music_rows:
        return
    narration_track = next(
        track for track in content["tracks"] if track["type"] == "audio"
    )
    if not narration_track.get("segments"):
        raise ValueError("Narration track chua co segment de lam mau BGM")
    template_segment = narration_track["segments"][0]
    _, template_audio = _find_material(content, template_segment["material_id"])

    music_tracks = []
    track_ends: list[float] = []
    audios = []
    for row in sorted(
        music_rows, key=lambda item: float(item.get("timeline_start", 0.0))
    ):
        audio_file = (package_dir / row["file"]).resolve()
        if not audio_file.is_file():
            raise FileNotFoundError(
                f"Khong tim thay file nhac nen: {audio_file}"
            )
        source_duration = _microseconds(float(row["source_duration"]))
        start_value = float(row.get("timeline_start", 0.0))
        start = _microseconds(start_value) if start_value > 0 else 0
        audio = copy.deepcopy(template_audio)
        audio["id"] = _uuid()
        audio["path"] = _capcut_path(audio_file)
        audio["duration"] = source_duration
        audio["name"] = audio_file.name
        audio["material_name"] = audio_file.name
        audios.append(audio)

        segment = copy.deepcopy(template_segment)
        segment["id"] = _uuid()
        segment["material_id"] = audio["id"]
        source_start = float(row.get("source_start", 0.0))
        segment["source_timerange"] = {
            "start": _microseconds(source_start) if source_start > 0 else 0,
            "duration": source_duration,
        }
        segment["target_timerange"] = {
            "start": start,
            "duration": _microseconds(float(row["duration"])),
        }
        volume = float(row.get("volume", 0.15))
        segment["volume"] = volume
        segment["last_nonzero_volume"] = volume
        segment["is_loop"] = False
        segment["extra_material_refs"] = []
        end_value = start_value + float(row["duration"])
        track_index = next(
            (
                index
                for index, track_end in enumerate(track_ends)
                if track_end <= start_value + 1e-6
            ),
            None,
        )
        if track_index is None:
            music_track = copy.deepcopy(narration_track)
            music_track["id"] = _uuid()
            music_track["segments"] = []
            music_tracks.append(music_track)
            track_ends.append(0.0)
            track_index = len(music_tracks) - 1
        music_tracks[track_index]["segments"].append(segment)
        track_ends[track_index] = end_value

    content["materials"]["audios"].extend(audios)
    content["tracks"].extend(music_tracks)


def _replace_captions(
    content: dict,
    captions_file: Path,
) -> None:
    cues = parse_srt(captions_file)
    if not cues:
        return
    text_track = next(
        (
            track
            for track in content["tracks"]
            if track["type"] == "text"
        ),
        None,
    )
    if text_track is None or not text_track.get("segments"):
        return
    template_segment = text_track["segments"][0]
    _, template_text_template = _find_material(
        content, template_segment["material_id"]
    )
    info = template_text_template["text_info_resources"][0]
    _, template_text = _find_material(content, info["text_material_id"])
    animation_id = template_segment["extra_material_refs"][0]
    _, template_animation = _find_material(content, animation_id)
    old_template_ids = {
        segment["material_id"]
        for segment in text_track["segments"]
    }
    old_animation_ids = {
        ref_id
        for segment in text_track["segments"]
        for ref_id in segment.get("extra_material_refs", [])
    }
    old_text_ids = set()
    for text_template in content["materials"]["text_templates"]:
        if text_template.get("id") not in old_template_ids:
            continue
        old_text_ids.update(
            info.get("text_material_id")
            for info in text_template.get("text_info_resources", [])
            if info.get("text_material_id")
        )

    text_templates = []
    texts = []
    animations = []
    segments = []
    for cue in cues:
        duration = _microseconds(cue.end - cue.start)
        start = _microseconds(cue.start) if cue.start > 0 else 0
        text = copy.deepcopy(template_text)
        text["id"] = _uuid()
        _set_caption_text(text, cue.text)
        texts.append(text)

        animation = copy.deepcopy(template_animation)
        animation["id"] = _uuid()
        for item in animation.get("animations", []):
            item["start"] = 0
            item["duration"] = duration
        animations.append(animation)

        text_template = copy.deepcopy(template_text_template)
        text_template["id"] = _uuid()
        text_info = text_template["text_info_resources"][0]
        text_info["id"] = _uuid()
        text_info["text_material_id"] = text["id"]
        text_info["extra_material_refs"] = [animation["id"]]
        text_info["attach_info"]["start_time"] = 0
        text_info["attach_info"]["duration"] = duration
        text_templates.append(text_template)

        segment = copy.deepcopy(template_segment)
        segment["id"] = _uuid()
        segment["material_id"] = text_template["id"]
        segment["extra_material_refs"] = [animation["id"]]
        segment["target_timerange"] = {
            "start": start,
            "duration": duration,
        }
        segments.append(segment)

    content["materials"]["texts"] = [
        item
        for item in content["materials"]["texts"]
        if item.get("id") not in old_text_ids
    ] + texts
    content["materials"]["text_templates"] = [
        item
        for item in content["materials"]["text_templates"]
        if item.get("id") not in old_template_ids
    ] + text_templates
    content["materials"]["material_animations"] = [
        item
        for item in content["materials"]["material_animations"]
        if item.get("id") not in old_animation_ids
    ] + animations
    text_track["segments"] = segments


def _stretch_template_tracks(content: dict, duration: int) -> None:
    for track in content["tracks"]:
        if track["type"] != "effect":
            continue
        for segment in track.get("segments", []):
            if segment.get("target_timerange", {}).get("start", 0) == 0:
                segment["target_timerange"]["duration"] = duration


def _update_draft_materials(
    meta: dict,
    scene_rows: list[dict],
    package_dir: Path,
    duration: int,
    audio_rows: list[dict],
    music_rows: list[dict],
) -> None:
    groups = meta.get("draft_materials", [])
    for group in groups:
        values = group.get("value", [])
        non_paths = [item for item in values if not item.get("file_Path")]
        video_sample = next(
            (
                item for item in values
                if str(item.get("file_Path", "")).lower().endswith(".mp4")
            ),
            None,
        )
        audio_sample = next(
            (
                item for item in values
                if str(item.get("file_Path", "")).lower().endswith(
                    (".mp3", ".wav", ".m4a", ".aac")
                )
            ),
            None,
        )
        if video_sample is None and audio_sample is None:
            continue
        rebuilt = non_paths
        if video_sample is not None:
            for row in scene_rows:
                path = (package_dir / row["file"]).resolve()
                item = copy.deepcopy(video_sample)
                item["file_Path"] = _capcut_path(path)
                item["duration"] = _microseconds(float(row["duration"]))
                item["width"] = 1920
                item["height"] = 1080
                item["extra_info"] = path.name
                rebuilt.append(item)
        if audio_sample is not None:
            source_rows = (audio_rows or [
                {
                    "file": "narration.wav",
                    "duration": duration / CAPCUT_TIMEBASE,
                }
            ]) + music_rows
            for row in source_rows:
                path = package_dir / row["file"]
                item = copy.deepcopy(audio_sample)
                item["file_Path"] = _capcut_path(path)
                item["duration"] = _microseconds(
                    float(row["duration"])
                )
                item["extra_info"] = path.name
                rebuilt.append(item)
        group["value"] = rebuilt


def _content_targets(draft_dir: Path) -> list[Path]:
    targets = [
        draft_dir / "draft_content.json",
        draft_dir / "draft_content.json.bak",
        draft_dir / "template-2.tmp",
    ]
    timelines = draft_dir / "Timelines"
    if timelines.is_dir():
        for timeline in timelines.iterdir():
            if not timeline.is_dir():
                continue
            targets.extend(
                [
                    timeline / "draft_content.json",
                    timeline / "draft_content.json.bak",
                    timeline / "template-2.tmp",
                ]
            )
    return [path for path in targets if path.exists()]


def _default_registry_file() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Không xác định được LOCALAPPDATA của CapCut")
    return (
        Path(local_app_data)
        / "CapCut"
        / "User Data"
        / "Projects"
        / "com.lveditor.draft"
        / "root_meta_info.json"
    )


def _register_draft(
    registry_file: Path,
    original_draft_id: str,
    meta: dict,
    draft_dir: Path,
    duration: int,
    material_size: int,
    replace_existing: bool = False,
) -> None:
    registry = _load_json(registry_file)
    entries = registry.get("all_draft_store", [])
    source = next(
        (
            entry for entry in entries
            if entry.get("draft_id") == original_draft_id
        ),
        {},
    )
    entry = copy.deepcopy(source)
    entry.update(
        {
            "draft_id": meta["draft_id"],
            "draft_name": meta["draft_name"],
            "draft_fold_path": _capcut_path(draft_dir),
            "draft_root_path": _capcut_path(draft_dir.parent),
            "draft_json_file": _capcut_path(
                draft_dir / "draft_content.json"
            ),
            "draft_cover": _capcut_path(draft_dir / "draft_cover.jpg"),
            "tm_draft_create": meta["tm_draft_create"],
            "tm_draft_modified": meta["tm_draft_modified"],
            "tm_duration": duration,
            "draft_timeline_materials_size": material_size,
            "streaming_edit_draft_ready": True,
        }
    )
    if replace_existing:
        target_path = _capcut_path(draft_dir).lower()
        entries = [
            item
            for item in entries
            if (
                str(item.get("draft_fold_path", "")).lower()
                != target_path
                and item.get("draft_id") != meta["draft_id"]
            )
        ]
    entries.append(entry)
    registry["all_draft_store"] = entries
    if (
        not replace_existing
        and isinstance(registry.get("draft_ids"), int)
    ):
        registry["draft_ids"] += 1

    backup = registry_file.with_name(
        registry_file.name + ".capcut_adapter.bak"
    )
    if not backup.exists():
        shutil.copy2(registry_file, backup)
    temporary = registry_file.with_name(
        registry_file.name + ".capcut_adapter.tmp"
    )
    _write_json(temporary, registry)
    os.replace(temporary, registry_file)


def create_capcut_draft(
    package_dir: Path,
    template_dir: Path,
    draft_name: str,
    *,
    drafts_root: Path | None = None,
    registry_file: Path | None = None,
    register: bool = True,
    replace_existing: bool = False,
) -> Path:
    package_dir = package_dir.resolve()
    template_dir = template_dir.resolve()
    safe_name = re.sub(r'[<>:"/\\|?*]+', "-", draft_name).strip(" .")
    if not safe_name:
        raise ValueError("Tên Draft CapCut không hợp lệ")
    if not (template_dir / "draft_content.json").is_file():
        raise FileNotFoundError(
            f"Template CapCut thiếu draft_content.json: {template_dir}"
        )
    if not (package_dir / "capcut_manifest.json").is_file():
        raise FileNotFoundError(
            f"Gói CapCut thiếu capcut_manifest.json: {package_dir}"
        )
    if register:
        _assert_capcut_closed()

    manifest = _load_json(package_dir / "capcut_manifest.json")
    scene_rows = manifest["tracks"]["video"]
    audio_rows = manifest["tracks"].get("audio_sections", [])
    music_rows = manifest["tracks"].get("background_music", [])
    captions_enabled = bool(
        manifest["tracks"].get("captions", {}).get("enabled", True)
    )
    duration = _microseconds(float(manifest["canvas"]["duration"]))
    root = (drafts_root or template_dir.parent).resolve()
    target = root / safe_name
    replaced_meta = None
    backup_target = None
    if target.exists():
        owned_marker = target / "Resources" / "CapCutAdapter"
        if not replace_existing or not owned_marker.is_dir():
            raise FileExistsError(
                "Draft CapCut đã tồn tại nhưng không được xác nhận là "
                f"Draft do ứng dụng tạo: {target}"
            )
        replaced_meta = _load_json(target / "draft_meta_info.json")
        backup_target = root / f".{safe_name}.capcut_adapter_backup"
        if backup_target.exists():
            raise FileExistsError(
                f"Backup Draft đang tồn tại, chưa thể thay thế: "
                f"{backup_target}"
            )
        target.rename(backup_target)
    shutil.copytree(template_dir, target)
    for stale_mini_draft in target.glob(
        "Timelines/*/attachment/patch/mini_draft.json"
    ):
        stale_mini_draft.unlink()
    embedded_package = target / "Resources" / "CapCutAdapter"
    embedded_package.mkdir(parents=True, exist_ok=True)
    embedded_scenes = embedded_package / "scenes"
    embedded_scenes.mkdir()
    for row in scene_rows:
        source_scene = package_dir / row["file"]
        shutil.copy2(
            source_scene,
            embedded_scenes / source_scene.name,
        )
    shutil.copy2(package_dir / "narration.wav", embedded_package / "narration.wav")
    captions_file = package_dir / "captions.srt"
    if captions_file.is_file():
        shutil.copy2(captions_file, embedded_package / captions_file.name)
    if audio_rows:
        embedded_audio = embedded_package / "audio_sections"
        embedded_audio.mkdir()
        for row in audio_rows:
            source_audio = package_dir / row["file"]
            shutil.copy2(
                source_audio,
                embedded_audio / source_audio.name,
            )
    if music_rows:
        embedded_music = embedded_package / "music"
        embedded_music.mkdir()
        for row in music_rows:
            source_music = package_dir / row["file"]
            shutil.copy2(
                source_music,
                embedded_music / source_music.name,
            )

    content_path = target / "draft_content.json"
    content = _load_json(content_path)
    if int(content.get("version", 0)) != SUPPORTED_TEMPLATE_VERSION:
        raise ValueError(
            "Template CapCut không đúng schema đã kiểm thử "
            f"({SUPPORTED_TEMPLATE_VERSION})"
        )
    content["name"] = safe_name
    content["duration"] = duration
    content["canvas_config"]["width"] = int(manifest["canvas"]["width"])
    content["canvas_config"]["height"] = int(manifest["canvas"]["height"])
    content["fps"] = float(manifest["canvas"]["fps"])
    content["path"] = _capcut_path(target)
    _replace_video_track(content, embedded_package, scene_rows)
    _replace_audio_track(
        content,
        embedded_package,
        audio_rows,
        duration,
    )
    _add_background_music_track(content, embedded_package, music_rows)
    embedded_captions = embedded_package / "captions.srt"
    if captions_enabled and embedded_captions.is_file():
        _replace_captions(content, embedded_captions)
    _stretch_template_tracks(content, duration)
    for path in _content_targets(target):
        _write_json(path, content)

    meta_path = target / "draft_meta_info.json"
    meta = _load_json(meta_path)
    original_draft_id = str(meta["draft_id"])
    now = time.time_ns() // 1000
    meta["draft_id"] = (
        str(replaced_meta["draft_id"])
        if replaced_meta is not None
        else _uuid()
    )
    meta["draft_name"] = safe_name
    meta["draft_fold_path"] = _capcut_path(target)
    meta["draft_root_path"] = _capcut_path(root)
    meta["draft_cover"] = _capcut_path(target / "draft_cover.jpg")
    meta["tm_draft_create"] = (
        int(replaced_meta.get("tm_draft_create", now))
        if replaced_meta is not None
        else now
    )
    meta["tm_draft_modified"] = now
    meta["tm_duration"] = duration
    _update_draft_materials(
        meta,
        scene_rows,
        embedded_package,
        duration,
        audio_rows,
        music_rows,
    )
    material_size = sum(
        path.stat().st_size
        for path in [
            *(embedded_package / row["file"] for row in scene_rows),
            *(
                embedded_package / row["file"]
                for row in audio_rows
            ),
            *(
                embedded_package / row["file"]
                for row in music_rows
            ),
            *(
                []
                if audio_rows
                else [embedded_package / "narration.wav"]
            ),
        ]
        if path.is_file()
    )
    meta["draft_timeline_materials_size_"] = material_size
    _write_json(meta_path, meta)

    if register:
        _register_draft(
            registry_file or _default_registry_file(),
            original_draft_id,
            meta,
            target,
            duration,
            material_size,
            replace_existing=replace_existing,
        )
    if backup_target is not None and backup_target.exists():
        shutil.rmtree(backup_target)
    manifest["capcut_draft"] = {
        "name": safe_name,
        "path": _capcut_path(target),
        "template": _capcut_path(template_dir),
        "template_schema": SUPPORTED_TEMPLATE_VERSION,
        "template_app_version": SUPPORTED_APP_VERSION,
        "registered": register,
        "media_root": _capcut_path(embedded_package),
    }
    _write_json(package_dir / "capcut_manifest.json", manifest)
    print(f"CapCut draft ready: {target}")
    return target
