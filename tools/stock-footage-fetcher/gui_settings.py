"""Portable settings and API-key persistence for the desktop GUI."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


APP_DIR_NAME = "stock_footage_finder"


def source_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return source_root()


def data_dir() -> Path:
    path = portable_root() / "data" / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_cache_dir() -> Path:
    if getattr(sys, "frozen", False):
        path = data_dir() / "model-cache"
    else:
        path = (
            source_root().parent
            / "footage-video-builder"
            / ".cache"
            / "huggingface"
            / "hub"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def env_path() -> Path:
    return portable_root() / ".env"


def icon_path() -> Path:
    bundled = source_root() / "assets" / "icons" / "app_icon.png"
    if bundled.is_file():
        return bundled
    return source_root().parent / "footage-finder-ai" / "assets" / "icons" / "app_icon.png"


@dataclass
class GuiSettings:
    use_pexels: bool = True
    use_pixabay: bool = True
    max_queries: int = 2
    max_pages: int = 1
    per_page: int = 40
    workers: int = 2
    clips_per_beat: int = 2
    candidate_pool: int = 24
    shortlist: int = 6
    min_duration: float = 8.0
    min_score: float = 0.18
    min_width: int = 1920
    min_height: int = 1080
    max_pixabay_downloads: int = 20
    dry_run: bool = False
    last_project_dir: str = ""


def _clamp(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize(settings: GuiSettings) -> GuiSettings:
    settings.use_pexels = bool(settings.use_pexels)
    settings.use_pixabay = bool(settings.use_pixabay)
    settings.max_queries = _clamp(settings.max_queries, 1, 5, 2)
    settings.max_pages = _clamp(settings.max_pages, 1, 10, 1)
    settings.per_page = _clamp(settings.per_page, 3, 80, 40)
    settings.workers = _clamp(settings.workers, 1, 8, 2)
    settings.clips_per_beat = _clamp(settings.clips_per_beat, 1, 4, 2)
    settings.candidate_pool = _clamp(settings.candidate_pool, 4, 100, 24)
    settings.shortlist = _clamp(settings.shortlist, 1, 30, 6)
    settings.min_width = _clamp(settings.min_width, 640, 7680, 1920)
    settings.min_height = _clamp(settings.min_height, 360, 4320, 1080)
    settings.max_pixabay_downloads = _clamp(
        settings.max_pixabay_downloads, 0, 500, 20
    )
    try:
        settings.min_duration = max(1.0, min(120.0, float(settings.min_duration)))
    except (TypeError, ValueError):
        settings.min_duration = 8.0
    try:
        settings.min_score = max(-1.0, min(1.0, float(settings.min_score)))
    except (TypeError, ValueError):
        settings.min_score = 0.18
    settings.dry_run = bool(settings.dry_run)
    settings.last_project_dir = str(settings.last_project_dir or "").strip()
    return settings


def load_settings() -> GuiSettings:
    path = settings_path()
    if not path.is_file():
        return GuiSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return GuiSettings()
    valid = {item.name for item in fields(GuiSettings)}
    clean = {key: value for key, value in raw.items() if key in valid}
    return normalize(GuiSettings(**clean))


def save_settings(settings: GuiSettings) -> None:
    path = settings_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(normalize(settings)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_api_keys() -> tuple[str, str]:
    values = {
        "PEXELS_API_KEY": os.environ.get("PEXELS_API_KEY", ""),
        "PIXABAY_API_KEY": os.environ.get("PIXABAY_API_KEY", ""),
    }
    path = env_path()
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key in values and not values[key]:
                values[key] = value
    return values["PEXELS_API_KEY"], values["PIXABAY_API_KEY"]


def save_api_keys(pexels_key: str, pixabay_key: str) -> None:
    path = env_path()
    existing: list[str] = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8-sig").splitlines()
    replacements = {
        "PEXELS_API_KEY": pexels_key.strip(),
        "PIXABAY_API_KEY": pixabay_key.strip(),
    }
    result: list[str] = []
    handled: set[str] = set()
    for raw in existing:
        match = None
        if "=" in raw and not raw.lstrip().startswith("#"):
            match = raw.split("=", 1)[0].strip()
        if match in replacements:
            value = replacements[match]
            result.append(f"{match}={value}" if value else f"# {match}=")
            handled.add(match)
        else:
            result.append(raw)
    for key, value in replacements.items():
        if key not in handled:
            result.append(f"{key}={value}" if value else f"# {key}=")
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
