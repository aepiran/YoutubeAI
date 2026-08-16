"""Packaged text resources used by StoryFlow workflows."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def _external_base_dna(filename: str) -> str:
    """Load an editable BASE DNA beside the source tree when available."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "BASE" / filename
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8-sig")
    return ""


def builtin_background_music_dna() -> str:
    """Return the Background Music DNA bundled with the installed build."""

    external = _external_base_dna("DNA_background_music.md")
    if external:
        return external
    return (
        files("storyflow_studio.assets")
        .joinpath("dna", "background_music.md")
        .read_text(encoding="utf-8")
    )


def builtin_screen_subtitle_dna() -> str:
    """Return the Screen SRT DNA bundled with the installed build."""

    external = _external_base_dna("DNA_screen_subtitles.md")
    if external:
        return external
    return (
        files("storyflow_studio.assets")
        .joinpath("dna", "screen_subtitles.md")
        .read_text(encoding="utf-8")
    )
