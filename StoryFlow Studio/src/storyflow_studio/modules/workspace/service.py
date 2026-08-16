"""Safe creation and loading of StoryFlow projects."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...core.settings import AppSettings


PROJECT_SCHEMA_VERSION = 1
FOLDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class ProjectError(RuntimeError):
    pass


@dataclass(slots=True)
class ProjectPaths:
    raw_script: str = "script.txt"
    tts_script: str = "script_tts.txt"
    audio_dir: str = "audio"
    audio_file: str = "narration.mp3"
    subtitle_file: str = "narration.srt"
    screen_subtitle_file: str = "screen.srt"
    beat_file: str = "footage.csv"
    music_cue_file: str = "cue_music.csv"
    background_music_file: str = "audio/background_music.mp3"
    footage_dir: str = "video"
    footage_manifest: str = "selected-footage.json"
    footage_manifest_csv: str = "selected-footage.csv"
    beat_timing_file: str = ".storyflow/beat_timing.json"
    video_timeline_file: str = ".storyflow/video-builder/timeline.json"
    video_timeline_csv: str = "video_timeline.csv"
    final_video_file: str = "output/final_video.mp4"
    attribution_file: str = "output/attribution.csv"
    capcut_package_dir: str = "output/capcut_package"


@dataclass(slots=True)
class ProjectManifest:
    schema_version: int
    project_id: str
    name: str
    created_at: str
    updated_at: str
    paths: ProjectPaths
    description: str = ""
    stages: dict[str, str] = field(
        default_factory=lambda: {
            "tts_script": "pending",
            "voice": "pending",
            "beat": "pending",
            "music": "pending",
            "footage": "pending",
            "video_plan": "pending",
            "video_render": "pending",
        }
    )


@dataclass(frozen=True, slots=True)
class Project:
    root: Path
    manifest: ProjectManifest

    @property
    def metadata_dir(self) -> Path:
        return self.root / ".storyflow"

    @property
    def manifest_path(self) -> Path:
        return self.metadata_dir / "project.json"

    def path_for(self, name: str) -> Path:
        paths = self.manifest.paths
        if name == "raw_script":
            relative = Path(paths.raw_script)
        elif name == "tts_script":
            relative = Path(paths.tts_script)
        elif name == "audio_dir":
            relative = Path(paths.audio_dir)
        elif name == "audio_file":
            relative = Path(paths.audio_dir) / paths.audio_file
        elif name == "subtitle_file":
            relative = Path(paths.audio_dir) / paths.subtitle_file
        elif name == "screen_subtitle_file":
            relative = Path(paths.audio_dir) / paths.screen_subtitle_file
        elif name == "beat_file":
            relative = Path(paths.beat_file)
        elif name == "music_cue_file":
            relative = Path("audio") / paths.music_cue_file
        elif name == "background_music_file":
            relative = Path(paths.background_music_file)
        elif name == "footage_dir":
            relative = Path(paths.footage_dir)
        elif name == "footage_manifest":
            relative = Path(paths.footage_manifest)
        elif name == "footage_manifest_csv":
            relative = Path(paths.footage_manifest_csv)
        elif name == "beat_timing_file":
            relative = Path(paths.beat_timing_file)
        elif name == "video_timeline_file":
            relative = Path(paths.video_timeline_file)
        elif name == "video_timeline_csv":
            relative = Path(paths.video_timeline_csv)
        elif name == "final_video_file":
            relative = Path(paths.final_video_file)
        elif name == "attribution_file":
            relative = Path(paths.attribution_file)
        elif name == "capcut_package_dir":
            relative = Path(paths.capcut_package_dir)
        else:
            raise KeyError(name)
        return (self.root / relative).resolve()


def _footage_project_complete(project: Project) -> bool:
    manifest = project.path_for("footage_manifest")
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("complete") is True


def slugify_project_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return slug[:80] or "project"


class WorkspaceService:
    def create_project(
        self,
        workspace_root: str | Path,
        name: str,
        folder_name: str,
        settings: AppSettings,
        *,
        description: str = "",
    ) -> Project:
        clean_name = name.strip()
        clean_description = description.strip()
        if not clean_name:
            raise ProjectError("Project Name không được để trống.")
        if len(clean_description) > 2000:
            raise ProjectError("Project Description không được dài quá 2.000 ký tự.")
        clean_folder = self.validate_folder_name(folder_name)
        root = Path(workspace_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise ProjectError(f"Workspace Root không hợp lệ: {root}")
        target = (root / clean_folder).resolve()
        if target.parent != root:
            raise ProjectError("Project phải nằm trực tiếp trong Workspace Root.")
        if target.exists():
            raise ProjectError(
                f"Project folder đã tồn tại: {target.name}. Hãy dùng Open Project."
            )

        paths = self._paths_from_settings(settings)
        now = datetime.now(UTC).isoformat()
        manifest = ProjectManifest(
            schema_version=PROJECT_SCHEMA_VERSION,
            project_id=str(uuid.uuid4()),
            name=clean_name,
            created_at=now,
            updated_at=now,
            paths=paths,
            description=clean_description,
        )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".storyflow-new-{clean_folder}-", dir=root)
        )
        try:
            self._validate_paths(temporary, paths)
            (temporary / paths.audio_dir).mkdir(parents=True, exist_ok=True)
            (temporary / paths.background_music_file).parent.mkdir(
                parents=True, exist_ok=True
            )
            metadata = temporary / ".storyflow"
            (metadata / "logs").mkdir(parents=True, exist_ok=True)
            (metadata / "cache").mkdir(parents=True, exist_ok=True)
            self._write_manifest(metadata / "project.json", manifest)
            os.replace(temporary, target)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return Project(target, manifest)

    def open_project(self, project_dir: str | Path) -> Project:
        root = Path(project_dir).expanduser().resolve()
        manifest_path = root / ".storyflow" / "project.json"
        if not root.is_dir() or not manifest_path.is_file():
            raise ProjectError("Thư mục đã chọn không phải StoryFlow Project.")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"Không đọc được project manifest: {exc}") from exc
        manifest = self._manifest_from_json(raw)
        self._validate_paths(root, manifest.paths)
        project = Project(root, manifest)
        discovered = self._discover_stages(project)
        if discovered != manifest.stages:
            manifest.stages = discovered
            manifest.updated_at = datetime.now(UTC).isoformat()
            self._write_manifest(manifest_path, manifest)
        return project

    @staticmethod
    def validate_folder_name(value: str) -> str:
        clean = value.strip()
        if not FOLDER_PATTERN.fullmatch(clean) or clean in {".", ".."}:
            raise ProjectError(
                "Folder Name chỉ dùng chữ, số, dấu gạch ngang hoặc gạch dưới."
            )
        return clean

    def _paths_from_settings(self, settings: AppSettings) -> ProjectPaths:
        tts = settings.tts.normalized()
        beat = settings.beat.normalized()
        paths = ProjectPaths(
            tts_script=tts.script_filename,
            audio_dir=tts.output_folder,
            audio_file=tts.audio_filename,
            subtitle_file=tts.subtitle_filename,
            beat_file=beat.output_filename,
        )
        self._validate_filename(paths.raw_script, "Raw Script Filename")
        self._validate_filename(paths.tts_script, "TTS Script Filename")
        self._validate_filename(paths.audio_file, "Audio Filename")
        self._validate_filename(paths.subtitle_file, "Subtitle Filename")
        self._validate_filename(paths.beat_file, "Beat Filename")
        return paths

    def _validate_paths(self, root: Path, paths: ProjectPaths) -> None:
        root = root.resolve()
        for label, relative in (
            ("raw_script", paths.raw_script),
            ("tts_script", paths.tts_script),
            ("audio_dir", paths.audio_dir),
            ("beat_file", paths.beat_file),
            ("audio_file", str(Path(paths.audio_dir) / paths.audio_file)),
            ("subtitle_file", str(Path(paths.audio_dir) / paths.subtitle_file)),
            (
                "screen_subtitle_file",
                str(Path(paths.audio_dir) / paths.screen_subtitle_file),
            ),
            ("music_cue_file", str(Path("audio") / paths.music_cue_file)),
            ("background_music_file", paths.background_music_file),
            ("footage_dir", paths.footage_dir),
            ("footage_manifest", paths.footage_manifest),
            ("footage_manifest_csv", paths.footage_manifest_csv),
            ("beat_timing_file", paths.beat_timing_file),
            ("video_timeline_file", paths.video_timeline_file),
            ("video_timeline_csv", paths.video_timeline_csv),
            ("final_video_file", paths.final_video_file),
            ("attribution_file", paths.attribution_file),
        ):
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ProjectError(f"Project path không an toàn ({label}): {relative}")
            resolved = (root / candidate).resolve()
            if not resolved.is_relative_to(root):
                raise ProjectError(f"Project path thoát ra ngoài project: {relative}")
        self._validate_filename(paths.raw_script, "raw_script")
        self._validate_filename(paths.tts_script, "tts_script")
        self._validate_filename(paths.audio_file, "audio_file")
        self._validate_filename(paths.subtitle_file, "subtitle_file")
        self._validate_filename(paths.screen_subtitle_file, "screen_subtitle_file")
        self._validate_filename(paths.beat_file, "beat_file")
        self._validate_filename(paths.music_cue_file, "music_cue_file")
        self._validate_filename(paths.footage_dir, "footage_dir")
        self._validate_filename(paths.footage_manifest, "footage_manifest")
        self._validate_filename(paths.footage_manifest_csv, "footage_manifest_csv")

    @staticmethod
    def _validate_filename(value: str, label: str) -> None:
        path = Path(value)
        if not value.strip() or path.name != value or value in {".", ".."}:
            raise ProjectError(f"{label} phải là một filename, không phải đường dẫn.")

    @staticmethod
    def _manifest_from_json(raw: Any) -> ProjectManifest:
        if not isinstance(raw, dict) or raw.get("schema_version") != PROJECT_SCHEMA_VERSION:
            raise ProjectError("Project manifest schema không được hỗ trợ.")
        paths_raw = raw.get("paths")
        if not isinstance(paths_raw, dict):
            raise ProjectError("Project manifest thiếu paths.")
        try:
            paths = ProjectPaths(
                raw_script=str(paths_raw["raw_script"]),
                tts_script=str(paths_raw["tts_script"]),
                audio_dir=str(paths_raw["audio_dir"]),
                audio_file=str(paths_raw["audio_file"]),
                subtitle_file=str(paths_raw["subtitle_file"]),
                screen_subtitle_file=str(
                    paths_raw.get("screen_subtitle_file", "screen.srt")
                ),
                beat_file=str(paths_raw["beat_file"]),
                music_cue_file=str(paths_raw.get("music_cue_file", "cue_music.csv")),
                background_music_file=str(
                    paths_raw.get(
                        "background_music_file",
                        "audio/background_music.mp3",
                    )
                ),
                footage_dir=str(paths_raw.get("footage_dir", "video")),
                footage_manifest=str(
                    paths_raw.get("footage_manifest", "selected-footage.json")
                ),
                footage_manifest_csv=str(
                    paths_raw.get("footage_manifest_csv", "selected-footage.csv")
                ),
                beat_timing_file=str(
                    paths_raw.get("beat_timing_file", ".storyflow/beat_timing.json")
                ),
                video_timeline_file=str(
                    paths_raw.get(
                        "video_timeline_file",
                        ".storyflow/video-builder/timeline.json",
                    )
                ),
                video_timeline_csv=str(
                    paths_raw.get("video_timeline_csv", "video_timeline.csv")
                ),
                final_video_file=str(
                    paths_raw.get("final_video_file", "output/final_video.mp4")
                ),
                attribution_file=str(
                    paths_raw.get("attribution_file", "output/attribution.csv")
                ),
                capcut_package_dir=str(
                    paths_raw.get("capcut_package_dir", "output/capcut_package")
                ),
            )
            name = str(raw["name"]).strip()
            project_id = str(raw["project_id"]).strip()
        except KeyError as exc:
            raise ProjectError(f"Project manifest thiếu field: {exc.args[0]}") from exc
        if not name or not project_id:
            raise ProjectError("Project manifest thiếu name hoặc project_id.")
        stages_raw = raw.get("stages", {})
        stages = {
            key: str(stages_raw.get(key, "pending"))
            for key in (
                "tts_script",
                "voice",
                "beat",
                "music",
                "footage",
                "video_plan",
                "video_render",
            )
        } if isinstance(stages_raw, dict) else {}
        return ProjectManifest(
            schema_version=PROJECT_SCHEMA_VERSION,
            project_id=project_id,
            name=name,
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            paths=paths,
            description=str(raw.get("description", "")).strip(),
            stages=stages,
        )

    @staticmethod
    def _discover_stages(project: Project) -> dict[str, str]:
        return {
            "tts_script": "completed" if project.path_for("tts_script").is_file() else "pending",
            "voice": "completed"
            if project.path_for("audio_file").is_file()
            and project.path_for("subtitle_file").is_file()
            and project.path_for("screen_subtitle_file").is_file()
            else "pending",
            "beat": "completed" if project.path_for("beat_file").is_file() else "pending",
            "music": "completed"
            if project.path_for("music_cue_file").is_file()
            and project.path_for("background_music_file").is_file()
            else "pending",
            "footage": "completed" if _footage_project_complete(project) else "pending",
            "video_plan": "completed"
            if project.path_for("video_timeline_file").is_file()
            and project.path_for("video_timeline_csv").is_file()
            else "pending",
            "video_render": "completed"
            if project.path_for("final_video_file").is_file()
            else "pending",
        }

    @staticmethod
    def _write_manifest(path: Path, manifest: ProjectManifest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(manifest)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=".project.json.",
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
