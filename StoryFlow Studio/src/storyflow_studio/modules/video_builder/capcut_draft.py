"""Create an editable CapCut Draft from a StoryFlow portable package.

The adapter deliberately starts from a user-supplied CapCut template. CapCut's
Draft schema is private and versioned, so cloning known-good materials/tracks is
safer than synthesizing undocumented JSON from scratch.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ...core.process import WINDOWS_NO_WINDOW


CAPCUT_TIMEBASE = 1_000_000
SUPPORTED_TEMPLATE_VERSION = 360000
SUPPORTED_APP_VERSION = "9.1.0"
OWNER_DIR = Path("Resources") / "StoryFlowStudio"


@dataclass(frozen=True, slots=True)
class CaptionCue:
    start: float
    end: float
    text: str


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
        creationflags=WINDOWS_NO_WINDOW,
    )
    if "CapCut.exe" in completed.stdout:
        raise RuntimeError(
            "Hãy đóng CapCut trước khi đăng ký Draft để tránh CapCut ghi đè registry."
        )


def _find_material(content: dict, material_id: str) -> tuple[str, dict]:
    for collection, values in content.get("materials", {}).items():
        for material in values or []:
            if material.get("id") == material_id:
                return collection, material
    raise ValueError(f"Template thiếu Material tham chiếu: {material_id}")


def _clone_refs(content: dict, refs: list[str]) -> list[str]:
    cloned_ids: list[str] = []
    for material_id in refs:
        collection, source = _find_material(content, material_id)
        cloned = copy.deepcopy(source)
        cloned["id"] = _uuid()
        content["materials"][collection].append(cloned)
        cloned_ids.append(cloned["id"])
    return cloned_ids


def _replace_video_track(content: dict, media_root: Path, rows: list[dict]) -> None:
    track = next(
        (item for item in content.get("tracks", []) if item.get("type") == "video"),
        None,
    )
    if track is None or not track.get("segments"):
        raise ValueError("Template CapCut chưa có video placeholder.")
    templates = track["segments"]
    template_materials = {
        segment["material_id"]: _find_material(content, segment["material_id"])[1]
        for segment in templates
    }
    old_ids = set(template_materials)
    videos: list[dict] = []
    segments: list[dict] = []
    canvas = content.get("canvas_config", {})
    width = int(canvas.get("width", 1920))
    height = int(canvas.get("height", 1080))
    for index, row in enumerate(rows):
        source = (media_root / str(row["file"])).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Không tìm thấy CapCut scene: {source}")
        template = templates[index % len(templates)]
        duration = _microseconds(float(row["duration"]))
        start_value = float(row.get("timeline_start", 0.0))
        start = _microseconds(start_value) if start_value > 0 else 0
        material = copy.deepcopy(template_materials[template["material_id"]])
        material.update(
            {
                "id": _uuid(),
                "path": _capcut_path(source),
                "duration": duration,
                "material_name": source.name,
                "name": source.name,
                "width": width,
                "height": height,
            }
        )
        segment = copy.deepcopy(template)
        segment.update(
            {
                "id": _uuid(),
                "material_id": material["id"],
                "source_timerange": {"start": 0, "duration": duration},
                "target_timerange": {"start": start, "duration": duration},
            }
        )
        segment["extra_material_refs"] = _clone_refs(
            content, list(template.get("extra_material_refs", []))
        )
        videos.append(material)
        segments.append(segment)
    content["materials"]["videos"] = [
        item
        for item in content["materials"].get("videos", [])
        if item.get("id") not in old_ids
    ] + videos
    track["segments"] = segments


def _audio_template(content: dict) -> tuple[dict, dict, dict]:
    tracks = [item for item in content.get("tracks", []) if item.get("type") == "audio"]
    if not tracks or not tracks[0].get("segments"):
        raise ValueError("Template CapCut chưa có audio placeholder.")
    track = tracks[0]
    segment = track["segments"][0]
    _, material = _find_material(content, segment["material_id"])
    return track, segment, material


def _replace_audio(
    content: dict,
    media_root: Path,
    narration_name: str,
    duration: int,
    music_name: str | None,
) -> None:
    track, template_segment, template_audio = _audio_template(content)
    old_audio_ids = {
        segment.get("material_id")
        for item in content.get("tracks", [])
        if item.get("type") == "audio"
        for segment in item.get("segments", [])
    }
    narration = (media_root / narration_name).resolve()
    if not narration.is_file():
        raise FileNotFoundError(f"Không tìm thấy narration: {narration}")
    material = copy.deepcopy(template_audio)
    material.update(
        {
            "id": _uuid(),
            "path": _capcut_path(narration),
            "duration": duration,
            "name": narration.name,
            "material_name": narration.name,
        }
    )
    segment = copy.deepcopy(template_segment)
    segment.update(
        {
            "id": _uuid(),
            "material_id": material["id"],
            "source_timerange": {"start": 0, "duration": duration},
            "target_timerange": {"start": 0, "duration": duration},
        }
    )
    segment["extra_material_refs"] = _clone_refs(
        content, list(template_segment.get("extra_material_refs", []))
    )
    track["segments"] = [segment]
    content["tracks"] = [
        item for item in content["tracks"] if item.get("type") != "audio" or item is track
    ]
    audios = [material]
    if music_name:
        music = (media_root / music_name).resolve()
        if music.is_file():
            music_material = copy.deepcopy(template_audio)
            music_material.update(
                {
                    "id": _uuid(),
                    "path": _capcut_path(music),
                    "duration": duration,
                    "name": music.name,
                    "material_name": music.name,
                }
            )
            music_segment = copy.deepcopy(template_segment)
            music_segment.update(
                {
                    "id": _uuid(),
                    "material_id": music_material["id"],
                    "source_timerange": {"start": 0, "duration": duration},
                    "target_timerange": {"start": 0, "duration": duration},
                    "volume": 1.0,
                    "last_nonzero_volume": 1.0,
                    "extra_material_refs": [],
                }
            )
            music_track = copy.deepcopy(track)
            music_track["id"] = _uuid()
            music_track["segments"] = [music_segment]
            content["tracks"].append(music_track)
            audios.append(music_material)
    content["materials"]["audios"] = [
        item
        for item in content["materials"].get("audios", [])
        if item.get("id") not in old_audio_ids
    ] + audios


def _parse_srt(path: Path) -> list[CaptionCue]:
    timestamp = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    cues: list[CaptionCue] = []
    for block in re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig")):
        lines = block.splitlines()
        match_index = next((i for i, line in enumerate(lines) if timestamp.search(line)), None)
        if match_index is None:
            continue
        match = timestamp.search(lines[match_index])
        assert match is not None
        values = tuple(map(int, match.groups()))
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        text = "\n".join(lines[match_index + 1 :]).strip()
        if text and end > start:
            cues.append(CaptionCue(start, end, text))
    return cues


def _set_text(material: dict, text: str) -> None:
    for field in ("content", "base_content"):
        raw = material.get(field)
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload["text"] = text
        for style in payload.get("styles", []):
            style["range"] = [0, len(text)]
        material[field] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for field in ("recognize_text", "translate_original_text"):
        if field in material:
            material[field] = re.sub(r"\s+", " ", text).strip()


def _replace_captions(content: dict, captions: Path) -> None:
    cues = _parse_srt(captions)
    track = next(
        (item for item in content.get("tracks", []) if item.get("type") == "text"),
        None,
    )
    if not cues or track is None or not track.get("segments"):
        return
    template_segment = track["segments"][0]
    collection, template_material = _find_material(content, template_segment["material_id"])
    direct = collection == "texts"
    text_template = None
    if direct:
        template_text = template_material
    else:
        text_template = template_material
        resources = text_template.get("text_info_resources", [])
        if not resources:
            return
        _, template_text = _find_material(content, resources[0]["text_material_id"])
    animation_source = None
    refs = list(template_segment.get("extra_material_refs", []))
    if refs:
        _, animation_source = _find_material(content, refs[0])
    old_segment_ids = {item.get("material_id") for item in track["segments"]}
    texts: list[dict] = []
    text_templates: list[dict] = []
    animations: list[dict] = []
    segments: list[dict] = []
    for cue in cues:
        duration = _microseconds(cue.end - cue.start)
        start = _microseconds(cue.start) if cue.start > 0 else 0
        text = copy.deepcopy(template_text)
        text["id"] = _uuid()
        _set_text(text, cue.text)
        texts.append(text)
        animation = None
        if animation_source is not None:
            animation = copy.deepcopy(animation_source)
            animation["id"] = _uuid()
            animations.append(animation)
        segment = copy.deepcopy(template_segment)
        segment["id"] = _uuid()
        segment["target_timerange"] = {"start": start, "duration": duration}
        segment["extra_material_refs"] = [] if animation is None else [animation["id"]]
        if direct:
            segment["material_id"] = text["id"]
        else:
            cloned_template = copy.deepcopy(text_template)
            cloned_template["id"] = _uuid()
            info = cloned_template["text_info_resources"][0]
            info["id"] = _uuid()
            info["text_material_id"] = text["id"]
            info["extra_material_refs"] = segment["extra_material_refs"]
            if isinstance(info.get("attach_info"), dict):
                info["attach_info"].update({"start_time": 0, "duration": duration})
            segment["material_id"] = cloned_template["id"]
            text_templates.append(cloned_template)
        segments.append(segment)
    content["materials"]["texts"] = [
        item for item in content["materials"].get("texts", []) if item.get("id") not in old_segment_ids
    ] + texts
    if not direct:
        content["materials"]["text_templates"] = [
            item for item in content["materials"].get("text_templates", [])
            if item.get("id") not in old_segment_ids
        ] + text_templates
    if animations:
        content["materials"].setdefault("material_animations", []).extend(animations)
    track["segments"] = segments


def _stretch_template_tracks(content: dict, duration: int) -> None:
    first_video = True
    for track in content.get("tracks", []):
        if track.get("type") == "video":
            if first_video:
                first_video = False
                continue
            for segment in track.get("segments", []):
                if segment.get("target_timerange", {}).get("start", 0) != 0:
                    continue
                try:
                    collection, material = _find_material(content, segment["material_id"])
                except (KeyError, ValueError):
                    continue
                if collection == "videos" and material.get("type") == "photo":
                    segment["target_timerange"]["duration"] = duration
                    segment.setdefault("source_timerange", {})["duration"] = duration
        elif track.get("type") == "effect":
            for segment in track.get("segments", []):
                if segment.get("target_timerange", {}).get("start", 0) == 0:
                    segment["target_timerange"]["duration"] = duration


def _content_targets(draft: Path) -> list[Path]:
    targets = [draft / "draft_content.json", draft / "draft_content.json.bak", draft / "template-2.tmp"]
    timelines = draft / "Timelines"
    if timelines.is_dir():
        for timeline in timelines.iterdir():
            if timeline.is_dir():
                targets.extend(
                    [timeline / "draft_content.json", timeline / "draft_content.json.bak", timeline / "template-2.tmp"]
                )
    return [path for path in targets if path.exists()]


def _update_draft_materials(
    meta: dict,
    media_root: Path,
    rows: list[dict],
    narration_name: str,
    music_name: str | None,
    duration: int,
) -> None:
    for group in meta.get("draft_materials", []):
        values = group.get("value", [])
        video_sample = next(
            (
                item
                for item in values
                if str(item.get("file_Path", "")).lower().endswith(".mp4")
            ),
            None,
        )
        audio_sample = next(
            (
                item
                for item in values
                if str(item.get("file_Path", "")).lower().endswith(
                    (".mp3", ".wav", ".m4a", ".aac")
                )
            ),
            None,
        )
        if video_sample is None and audio_sample is None:
            continue
        rebuilt = [item for item in values if not item.get("file_Path")]
        if video_sample is not None:
            for row in rows:
                source = (media_root / str(row["file"])).resolve()
                item = copy.deepcopy(video_sample)
                item.update(
                    {
                        "file_Path": _capcut_path(source),
                        "duration": _microseconds(float(row["duration"])),
                        "extra_info": source.name,
                    }
                )
                rebuilt.append(item)
        if audio_sample is not None:
            for name in (narration_name, music_name):
                if not name:
                    continue
                source = (media_root / name).resolve()
                if not source.is_file():
                    continue
                item = copy.deepcopy(audio_sample)
                item.update(
                    {
                        "file_Path": _capcut_path(source),
                        "duration": duration,
                        "extra_info": source.name,
                    }
                )
                rebuilt.append(item)
        group["value"] = rebuilt


def _default_registry_file() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("Không xác định được LOCALAPPDATA của CapCut.")
    return Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft" / "root_meta_info.json"


def _register_draft(registry_file: Path, original_id: str, meta: dict, draft: Path) -> None:
    if not registry_file.is_file():
        raise FileNotFoundError(f"Không tìm thấy CapCut registry: {registry_file}")
    registry = _load_json(registry_file)
    entries = registry.get("all_draft_store", [])
    source = next((item for item in entries if item.get("draft_id") == original_id), {})
    entry = copy.deepcopy(source)
    entry.update(
        {
            "draft_id": meta["draft_id"],
            "draft_name": meta["draft_name"],
            "draft_fold_path": _capcut_path(draft),
            "draft_root_path": _capcut_path(draft.parent),
            "draft_json_file": _capcut_path(draft / "draft_content.json"),
            "draft_cover": _capcut_path(draft / "draft_cover.jpg"),
            "tm_draft_create": meta["tm_draft_create"],
            "tm_draft_modified": meta["tm_draft_modified"],
            "tm_duration": meta["tm_duration"],
            "streaming_edit_draft_ready": True,
        }
    )
    target = _capcut_path(draft).lower()
    registry["all_draft_store"] = [
        item for item in entries
        if str(item.get("draft_fold_path", "")).lower() != target
        and item.get("draft_id") != meta["draft_id"]
    ] + [entry]
    backup = registry_file.with_name(registry_file.name + ".storyflow.bak")
    if not backup.exists():
        shutil.copy2(registry_file, backup)
    temporary = registry_file.with_name(registry_file.name + ".storyflow.tmp")
    _write_json(temporary, registry)
    os.replace(temporary, registry_file)


def create_capcut_draft(
    package_dir: Path,
    template_dir: Path,
    draft_name: str,
    *,
    drafts_root: Path | None = None,
    register: bool = False,
    replace_existing: bool = False,
) -> Path:
    package_dir = package_dir.resolve()
    template_dir = template_dir.resolve()
    safe_name = re.sub(r'[<>:"/\\|?*]+', "-", draft_name).strip(" .")
    if not safe_name:
        raise ValueError("Tên Draft CapCut không hợp lệ.")
    if not (template_dir / "draft_content.json").is_file() or not (template_dir / "draft_meta_info.json").is_file():
        raise FileNotFoundError("Template CapCut cần draft_content.json và draft_meta_info.json.")
    manifest_path = package_dir / "capcut_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Gói CapCut thiếu manifest: {manifest_path}")
    if register:
        _assert_capcut_closed()
    manifest = _load_json(manifest_path)
    rows = list(manifest["tracks"]["video"])
    canvas = manifest["canvas"]
    duration = _microseconds(float(canvas["duration_seconds"]))
    root = (drafts_root or template_dir.parent).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / safe_name
    if (
        target == template_dir
        or target.is_relative_to(template_dir)
        or template_dir.is_relative_to(target)
    ):
        raise ValueError(
            "Template Draft và Draft đích không được chứa lẫn nhau."
        )
    backup = root / f".{safe_name}.storyflow-backup"
    if backup.exists() and not target.exists():
        backup.rename(target)
    if target.exists():
        if not replace_existing or not (target / OWNER_DIR).is_dir():
            raise FileExistsError(
                f"Draft đã tồn tại và không được xác nhận thuộc StoryFlow: {target}"
            )
        if backup.exists():
            shutil.rmtree(backup)
        target.rename(backup)
    try:
        shutil.copytree(template_dir, target)
        media_root = target / OWNER_DIR
        if media_root.exists():
            shutil.rmtree(media_root)
        media_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir / "scenes", media_root / "scenes")
        for name in (
            manifest["tracks"].get("narration"),
            manifest["tracks"].get("captions"),
            manifest["tracks"].get("narration_timing"),
            manifest["tracks"].get("background_music"),
        ):
            if name and (package_dir / str(name)).is_file():
                shutil.copy2(package_dir / str(name), media_root / Path(str(name)).name)
        (media_root / "owner.json").write_text(
            json.dumps({"owner": "StoryFlow Studio", "project": manifest.get("project", "")}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        content = _load_json(target / "draft_content.json")
        version = int(content.get("version", 0))
        if version != SUPPORTED_TEMPLATE_VERSION:
            raise ValueError(
                f"Template CapCut schema {version} chưa được hỗ trợ; cần {SUPPORTED_TEMPLATE_VERSION} ({SUPPORTED_APP_VERSION})."
            )
        content["name"] = safe_name
        content["duration"] = duration
        content["path"] = _capcut_path(target)
        content.setdefault("canvas_config", {}).update(
            {"width": int(canvas["width"]), "height": int(canvas["height"])}
        )
        content["fps"] = float(canvas["fps"])
        _replace_video_track(content, media_root, rows)
        narration = Path(str(manifest["tracks"]["narration"])).name
        music_value = manifest["tracks"].get("background_music")
        music = Path(str(music_value)).name if music_value else None
        _replace_audio(content, media_root, narration, duration, music)
        captions_value = manifest["tracks"].get("captions")
        if captions_value:
            captions = media_root / Path(str(captions_value)).name
            if captions.is_file():
                _replace_captions(content, captions)
        _stretch_template_tracks(content, duration)
        for path in _content_targets(target):
            _write_json(path, content)
        meta_path = target / "draft_meta_info.json"
        meta = _load_json(meta_path)
        original_id = str(meta.get("draft_id", ""))
        replaced_meta = _load_json(backup / "draft_meta_info.json") if backup.exists() else None
        now = time.time_ns() // 1000
        meta.update(
            {
                "draft_id": str(replaced_meta.get("draft_id")) if replaced_meta else _uuid(),
                "draft_name": safe_name,
                "draft_fold_path": _capcut_path(target),
                "draft_root_path": _capcut_path(root),
                "draft_cover": _capcut_path(target / "draft_cover.jpg"),
                "tm_draft_create": int(replaced_meta.get("tm_draft_create", now)) if replaced_meta else now,
                "tm_draft_modified": now,
                "tm_duration": duration,
            }
        )
        _update_draft_materials(
            meta,
            media_root,
            rows,
            narration,
            music,
            duration,
        )
        _write_json(meta_path, meta)
        if register:
            _register_draft(_default_registry_file(), original_id, meta, target)
        if backup.exists():
            shutil.rmtree(backup)
        manifest["capcut_draft"] = {
            "name": safe_name,
            "path": _capcut_path(target),
            "template": _capcut_path(template_dir),
            "template_schema": SUPPORTED_TEMPLATE_VERSION,
            "template_app_version": SUPPORTED_APP_VERSION,
            "registered": register,
            "media_root": _capcut_path(media_root),
        }
        _write_json(manifest_path, manifest)
        return target
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise
