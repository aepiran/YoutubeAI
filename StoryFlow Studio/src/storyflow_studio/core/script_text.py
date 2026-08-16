"""Helpers for reading StoryFlow script documents."""

from __future__ import annotations

import re


SCRIPT_MARKER = re.compile(r"^[ \t]*SCRIPT[ \t]*:[ \t]*", re.IGNORECASE | re.MULTILINE)


def extract_script_body(content: str) -> str:
    """Return content after a line-leading SCRIPT: marker, when present."""

    match = SCRIPT_MARKER.search(content)
    if match is None:
        return content
    return content[match.end() :].lstrip("\r\n")
