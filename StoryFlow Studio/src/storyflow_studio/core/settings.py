"""Application-scoped StoryFlow settings with secrets stored separately."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .secrets import KeyringSecretStore, SecretStore


SETTINGS_SCHEMA_VERSION = 7
REASONING_EFFORTS = ("default", "low", "medium", "high", "xhigh")


@dataclass(slots=True)
class AISettings:
    model: str = ""
    reasoning_effort: str = "default"

    def normalized(self) -> "AISettings":
        effort = self.reasoning_effort.strip().lower()
        if effort not in REASONING_EFFORTS:
            effort = "default"
        return AISettings(self.model.strip(), effort)


@dataclass(slots=True)
class WorkspaceSettings:
    workspace_root: str = ""
    role_file: str = ""
    role_instructions: str = ""
    recent_projects: list[str] = field(default_factory=list)
    last_project: str = ""

    def normalized(self) -> "WorkspaceSettings":
        recent = []
        for value in self.recent_projects:
            clean = str(value).strip()
            if clean and clean not in recent:
                recent.append(clean)
        return WorkspaceSettings(
            workspace_root=self.workspace_root.strip(),
            role_file=self.role_file.strip(),
            role_instructions=self.role_instructions.strip(),
            recent_projects=recent[:12],
            last_project=self.last_project.strip(),
        )


@dataclass(slots=True)
class TTSSettings:
    dna_path: str = ""
    api_base_url: str = ""
    api_key: str = field(default="", repr=False, compare=False)
    provider: str = "minimax"
    voice_id: str = ""
    voice_model: str = "speech-2.8-hd"
    language: str = "English"
    speed: float = 1.10
    pitch: int = 0
    volume: float = 2.00
    enable_srt: bool = True
    timeout_seconds: int = 1800
    poll_interval_seconds: int = 3
    max_retry: int = 3
    script_filename: str = "script_tts.txt"
    output_folder: str = "audio"
    audio_filename: str = "narration.mp3"
    subtitle_filename: str = "narration.srt"
    overwrite_existing: bool = False

    def normalized(self) -> "TTSSettings":
        return TTSSettings(
            dna_path=self.dna_path.strip(),
            api_base_url=self.api_base_url.strip().rstrip("/"),
            api_key=self.api_key.strip(),
            provider=self.provider.strip() or "minimax",
            voice_id=self.voice_id.strip(),
            voice_model=self.voice_model.strip() or "speech-2.8-hd",
            language=self.language.strip() or "English",
            speed=max(0.5, min(2.0, float(self.speed))),
            pitch=max(-12, min(12, int(self.pitch))),
            volume=max(0.01, min(10.0, float(self.volume))),
            enable_srt=bool(self.enable_srt),
            timeout_seconds=max(1, min(86400, int(self.timeout_seconds))),
            poll_interval_seconds=max(1, min(300, int(self.poll_interval_seconds))),
            max_retry=max(1, min(20, int(self.max_retry))),
            script_filename=self.script_filename.strip() or "script_tts.txt",
            output_folder=self.output_folder.strip() or "audio",
            audio_filename=self.audio_filename.strip() or "narration.mp3",
            subtitle_filename=self.subtitle_filename.strip() or "narration.srt",
            overwrite_existing=bool(self.overwrite_existing),
        )


@dataclass(slots=True)
class BeatSettings:
    dna_path: str = ""
    output_filename: str = "footage.csv"

    def normalized(self) -> "BeatSettings":
        return BeatSettings(
            self.dna_path.strip(),
            self.output_filename.strip() or "footage.csv",
        )


@dataclass(slots=True)
class MusicSettings:
    dna_path: str = ""
    library_folder: str = ""
    enabled: bool = False

    def normalized(self) -> "MusicSettings":
        return MusicSettings(
            dna_path=self.dna_path.strip(),
            library_folder=self.library_folder.strip(),
            enabled=bool(self.enabled),
        )


@dataclass(slots=True)
class FootageSettings:
    use_pexels: bool = True
    use_pixabay: bool = False
    pexels_api_key: str = field(default="", repr=False, compare=False)
    pixabay_api_key: str = field(default="", repr=False, compare=False)
    max_queries: int = 2
    max_pages: int = 1
    per_page: int = 40
    clips_per_beat: int = 2
    min_duration: float = 8.0
    min_width: int = 1920
    min_height: int = 1080
    max_pixabay_downloads: int = 20
    dry_run: bool = False

    def normalized(self) -> "FootageSettings":
        return FootageSettings(
            use_pexels=bool(self.use_pexels),
            use_pixabay=bool(self.use_pixabay),
            pexels_api_key=self.pexels_api_key.strip(),
            pixabay_api_key=self.pixabay_api_key.strip(),
            max_queries=max(1, min(5, int(self.max_queries))),
            max_pages=max(1, min(10, int(self.max_pages))),
            per_page=max(3, min(80, int(self.per_page))),
            clips_per_beat=max(1, min(4, int(self.clips_per_beat))),
            min_duration=max(1.0, min(120.0, float(self.min_duration))),
            min_width=max(640, min(7680, int(self.min_width))),
            min_height=max(360, min(4320, int(self.min_height))),
            max_pixabay_downloads=max(
                0, min(500, int(self.max_pixabay_downloads))
            ),
            dry_run=bool(self.dry_run),
        )


@dataclass(slots=True)
class VideoBuilderSettings:
    resolution: str = "1080p"
    output_fps: int = 30
    analysis_workers: int = min(4, max(1, os.cpu_count() or 1))
    min_cut_seconds: float = 3.0
    target_cut_seconds: float = 4.0
    max_cut_seconds: float = 5.0
    minimum_video_minutes: float = 0.0
    transition_seconds: float = 0.36
    encoder_preset: str = "veryfast"
    visual_model: str = "disabled"
    local_models_only: bool = False
    scene_threshold: float = 0.32
    scene_min_seconds: float = 1.0

    def normalized(self) -> "VideoBuilderSettings":
        resolution = self.resolution.strip().lower()
        if resolution not in {"1080p", "720p"}:
            resolution = "1080p"
        minimum = max(1.0, min(30.0, float(self.min_cut_seconds)))
        target = max(minimum, min(30.0, float(self.target_cut_seconds)))
        maximum = max(target, min(60.0, float(self.max_cut_seconds)))
        preset = self.encoder_preset.strip().lower()
        if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
            preset = "veryfast"
        visual_model = self.visual_model.strip().lower()
        if visual_model not in {
            "disabled",
            "openai/clip-vit-base-patch32",
            "google/siglip2-base-patch16-224",
        }:
            visual_model = "disabled"
        return VideoBuilderSettings(
            resolution=resolution,
            output_fps=max(24, min(60, int(self.output_fps))),
            analysis_workers=max(1, min(16, int(self.analysis_workers))),
            min_cut_seconds=minimum,
            target_cut_seconds=target,
            max_cut_seconds=maximum,
            minimum_video_minutes=max(
                0.0, min(180.0, float(self.minimum_video_minutes))
            ),
            transition_seconds=max(
                0.0, min(2.0, float(self.transition_seconds))
            ),
            encoder_preset=preset,
            visual_model=visual_model,
            local_models_only=bool(self.local_models_only),
            scene_threshold=max(0.05, min(0.95, float(self.scene_threshold))),
            scene_min_seconds=max(0.5, min(10.0, float(self.scene_min_seconds))),
        )


@dataclass(slots=True)
class AppSettings:
    ai: AISettings = field(default_factory=AISettings)
    workspace: WorkspaceSettings = field(default_factory=WorkspaceSettings)
    tts: TTSSettings = field(default_factory=TTSSettings)
    beat: BeatSettings = field(default_factory=BeatSettings)
    music: MusicSettings = field(default_factory=MusicSettings)
    footage: FootageSettings = field(default_factory=FootageSettings)
    video_builder: VideoBuilderSettings = field(default_factory=VideoBuilderSettings)

    def normalized(self) -> "AppSettings":
        return AppSettings(
            self.ai.normalized(),
            self.workspace.normalized(),
            self.tts.normalized(),
            self.beat.normalized(),
            self.music.normalized(),
            self.footage.normalized(),
            self.video_builder.normalized(),
        )


def default_settings_path() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "StoryFlow Studio" / "settings.json"


class SettingsStore:
    def __init__(
        self,
        path: str | Path | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path else default_settings_path()
        self.secret_store = secret_store or KeyringSecretStore()

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def load(self) -> AppSettings:
        raw = self._read()
        ai_raw = raw.get("ai", {}) if isinstance(raw.get("ai", {}), dict) else {}
        workspace_raw = raw.get("workspace", {})
        workspace_raw = workspace_raw if isinstance(workspace_raw, dict) else {}
        tts_raw = raw.get("tts", {}) if isinstance(raw.get("tts", {}), dict) else {}
        beat_raw = raw.get("beat", {}) if isinstance(raw.get("beat", {}), dict) else {}
        music_raw = raw.get("music", {}) if isinstance(raw.get("music", {}), dict) else {}
        footage_raw = (
            raw.get("footage", {}) if isinstance(raw.get("footage", {}), dict) else {}
        )
        video_builder_raw = raw.get("video_builder", {})
        video_builder_raw = (
            video_builder_raw if isinstance(video_builder_raw, dict) else {}
        )
        recent_raw = workspace_raw.get("recent_projects", [])
        recent = [str(item) for item in recent_raw] if isinstance(recent_raw, list) else []
        defaults = TTSSettings()
        settings = AppSettings(
            ai=AISettings(
                str(ai_raw.get("model", "")),
                str(ai_raw.get("reasoning_effort", "default")),
            ),
            workspace=WorkspaceSettings(
                workspace_root=str(workspace_raw.get("workspace_root", "")),
                role_file=str(workspace_raw.get("role_file", "")),
                role_instructions=str(workspace_raw.get("role_instructions", "")),
                recent_projects=recent,
                last_project=str(workspace_raw.get("last_project", "")),
            ),
            tts=TTSSettings(
                dna_path=str(tts_raw.get("dna_path", "")),
                api_base_url=str(tts_raw.get("api_base_url", "")),
                api_key=self.secret_store.get("tts_api_key"),
                provider=str(tts_raw.get("provider", defaults.provider)),
                voice_id=str(tts_raw.get("voice_id", "")),
                voice_model=str(tts_raw.get("voice_model", defaults.voice_model)),
                language=str(tts_raw.get("language", defaults.language)),
                speed=_float(tts_raw.get("speed"), defaults.speed),
                pitch=_int(tts_raw.get("pitch"), defaults.pitch),
                volume=_float(tts_raw.get("volume"), defaults.volume),
                enable_srt=_bool(tts_raw.get("enable_srt"), True),
                timeout_seconds=_int(tts_raw.get("timeout_seconds"), defaults.timeout_seconds),
                poll_interval_seconds=_int(
                    tts_raw.get("poll_interval_seconds"), defaults.poll_interval_seconds
                ),
                max_retry=_int(tts_raw.get("max_retry"), defaults.max_retry),
                script_filename=str(tts_raw.get("script_filename", defaults.script_filename)),
                output_folder=str(tts_raw.get("output_folder", defaults.output_folder)),
                audio_filename=str(tts_raw.get("audio_filename", defaults.audio_filename)),
                subtitle_filename=str(
                    tts_raw.get("subtitle_filename", defaults.subtitle_filename)
                ),
                overwrite_existing=_bool(tts_raw.get("overwrite_existing"), False),
            ),
            beat=BeatSettings(
                str(beat_raw.get("dna_path", "")),
                str(beat_raw.get("output_filename", "footage.csv")),
            ),
            music=MusicSettings(
                str(music_raw.get("dna_path", "")),
                str(music_raw.get("library_folder", "")),
                _bool(music_raw.get("enabled"), False),
            ),
            footage=FootageSettings(
                use_pexels=_bool(footage_raw.get("use_pexels"), True),
                use_pixabay=_bool(footage_raw.get("use_pixabay"), False),
                pexels_api_key=self.secret_store.get("pexels_api_key"),
                pixabay_api_key=self.secret_store.get("pixabay_api_key"),
                max_queries=_int(footage_raw.get("max_queries"), 2),
                max_pages=_int(footage_raw.get("max_pages"), 1),
                per_page=_int(footage_raw.get("per_page"), 40),
                clips_per_beat=_int(footage_raw.get("clips_per_beat"), 2),
                min_duration=_float(footage_raw.get("min_duration"), 8.0),
                min_width=_int(footage_raw.get("min_width"), 1920),
                min_height=_int(footage_raw.get("min_height"), 1080),
                max_pixabay_downloads=_int(
                    footage_raw.get("max_pixabay_downloads"), 20
                ),
                dry_run=_bool(footage_raw.get("dry_run"), False),
            ),
            video_builder=VideoBuilderSettings(
                resolution=str(video_builder_raw.get("resolution", "1080p")),
                output_fps=_int(video_builder_raw.get("output_fps"), 30),
                analysis_workers=_int(
                    video_builder_raw.get("analysis_workers"),
                    min(4, max(1, os.cpu_count() or 1)),
                ),
                min_cut_seconds=_float(
                    video_builder_raw.get("min_cut_seconds"), 3.0
                ),
                target_cut_seconds=_float(
                    video_builder_raw.get("target_cut_seconds"), 4.0
                ),
                max_cut_seconds=_float(
                    video_builder_raw.get("max_cut_seconds"), 5.0
                ),
                minimum_video_minutes=_float(
                    video_builder_raw.get("minimum_video_minutes"), 0.0
                ),
                transition_seconds=_float(
                    video_builder_raw.get("transition_seconds"), 0.36
                ),
                encoder_preset=str(
                    video_builder_raw.get("encoder_preset", "veryfast")
                ),
                visual_model=str(
                    video_builder_raw.get("visual_model", "disabled")
                ),
                local_models_only=_bool(
                    video_builder_raw.get("local_models_only"), False
                ),
                scene_threshold=_float(
                    video_builder_raw.get("scene_threshold"), 0.32
                ),
                scene_min_seconds=_float(
                    video_builder_raw.get("scene_min_seconds"), 1.0
                ),
            ),
        )
        return settings.normalized()

    def save(self, settings: AppSettings) -> None:
        value = settings.normalized()
        if value.tts.api_key:
            self.secret_store.set("tts_api_key", value.tts.api_key)
        else:
            self.secret_store.delete("tts_api_key")
        tts_json = asdict(value.tts)
        tts_json.pop("api_key", None)
        for name, secret in (
            ("pexels_api_key", value.footage.pexels_api_key),
            ("pixabay_api_key", value.footage.pixabay_api_key),
        ):
            if secret:
                self.secret_store.set(name, secret)
            else:
                self.secret_store.delete(name)
        footage_json = asdict(value.footage)
        footage_json.pop("pexels_api_key", None)
        footage_json.pop("pixabay_api_key", None)
        self._atomic_write(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "ai": asdict(value.ai),
                "workspace": asdict(value.workspace),
                "tts": tts_json,
                "beat": asdict(value.beat),
                "music": asdict(value.music),
                "footage": footage_json,
                "video_builder": asdict(value.video_builder),
            }
        )

    def load_ai(self) -> AISettings:
        return self.load().ai

    def save_ai(self, settings: AISettings) -> None:
        raw = self._read()
        raw["schema_version"] = SETTINGS_SCHEMA_VERSION
        raw["ai"] = asdict(settings.normalized())
        self._atomic_write(raw)

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(handle.name)
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
