"""Windows-safe subprocess helpers for the GUI application."""

from __future__ import annotations

import os
import subprocess
from typing import Any


WINDOWS_NO_WINDOW = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
)


class _NoConsoleSubprocessProxy:
    """Delegate a subprocess module while hiding console child processes."""

    _storyflow_no_console = True

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def Popen(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802 - mirrors stdlib
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | WINDOWS_NO_WINDOW
        return self._delegate.Popen(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def hide_console_for_subprocess_owner(owner: Any) -> None:
    """Hide Windows consoles for a third-party module that owns `subprocess`."""

    if not WINDOWS_NO_WINDOW:
        return
    current = getattr(owner, "subprocess", None)
    if current is None or getattr(current, "_storyflow_no_console", False):
        return
    owner.subprocess = _NoConsoleSubprocessProxy(current)
