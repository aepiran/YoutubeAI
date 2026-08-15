"""Build metadata helpers for StoryFlow Studio."""

from __future__ import annotations

from importlib import metadata

from storyflow_studio import __version__ as source_version

BUILD_DISTRIBUTION = "storyflow-studio"


def application_version() -> str:
    """Return the installed build version, with a source-tree fallback."""

    try:
        return metadata.version(BUILD_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return source_version


def version_badge() -> str:
    """Return the compact version label shown in the desktop header."""

    version = application_version().strip()
    return version if version.lower().startswith("v") else f"v{version}"
