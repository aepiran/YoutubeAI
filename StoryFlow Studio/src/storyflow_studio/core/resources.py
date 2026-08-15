"""Packaged text resources used by StoryFlow workflows."""

from __future__ import annotations

from importlib.resources import files


def builtin_background_music_dna() -> str:
    """Return the Background Music DNA bundled with the installed build."""

    return (
        files("storyflow_studio.assets")
        .joinpath("dna", "background_music.md")
        .read_text(encoding="utf-8")
    )
