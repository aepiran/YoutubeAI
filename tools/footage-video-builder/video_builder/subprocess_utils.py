from __future__ import annotations

import os
import subprocess


_ORIGINAL_POPEN = subprocess.Popen
_PATCHED = False


def hidden_subprocess_kwargs() -> dict:
    """Keep child FFmpeg windows hidden on Windows GUI builds."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def install_hidden_subprocess_patch() -> None:
    """Hide console windows for subprocesses started by third-party libraries."""
    global _PATCHED
    if os.name != "nt" or _PATCHED:
        return

    def hidden_popen(*args, **kwargs):
        kwargs["creationflags"] = (
            int(kwargs.get("creationflags", 0))
            | subprocess.CREATE_NO_WINDOW
        )
        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
            kwargs["startupinfo"] = startupinfo
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return _ORIGINAL_POPEN(*args, **kwargs)

    subprocess.Popen = hidden_popen
    _PATCHED = True
