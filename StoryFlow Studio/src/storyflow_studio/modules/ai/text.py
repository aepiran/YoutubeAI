"""Shared cleanup for raw AI response text."""

from __future__ import annotations

import re


_MARKDOWN_FENCE = re.compile(
    r"\A```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t]*\Z",
    re.DOTALL,
)


def strip_markdown_fence(text: str) -> str:
    """Strip a single ```/```lang ... ``` wrapper some models add despite
    explicit no-fence instructions in the prompt (observed with Claude on
    JSON/plain-text responses that Codex reliably returned unwrapped).

    Only removes a clean single fence spanning the entire response; a
    response with just a stray backtick run on one side is left unchanged
    so the caller's existing fence check still catches it as malformed.
    """
    stripped = text.strip()
    match = _MARKDOWN_FENCE.match(stripped)
    return match.group("body").strip() if match else stripped
