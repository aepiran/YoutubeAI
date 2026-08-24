# -*- mode: python ; coding: utf-8 -*-

"""Canonical Windows PyInstaller definition for StoryFlow Studio."""

import shutil
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)


PROJECT_DIR = Path(SPECPATH).resolve()
SOURCE_DIR = PROJECT_DIR / "src"
APP_NAME = "StoryFlowStudio"

datas = collect_data_files("storyflow_studio")
codex_cli_datas, codex_cli_binaries, codex_cli_hiddenimports = collect_all(
    "codex_cli_bin"
)
datas += codex_cli_datas
for distribution in (
    "storyflow-studio",
    "openai-codex",
    "openai-codex-cli-bin",
    "keyring",
    "transformers",
    "huggingface-hub",
):
    datas += copy_metadata(distribution)

hiddenimports = []
for package in (
    "openai_codex",
    "keyring.backends",
    "transformers.models.clip",
    "transformers.models.siglip",
    "transformers.models.siglip2",
):
    hiddenimports += collect_submodules(package)
hiddenimports += codex_cli_hiddenimports

binaries = list(codex_cli_binaries)

# claude-agent-sdk is an optional dependency (Settings -> AI Provider ->
# Claude); only bundle it when the build environment has it installed, and
# never fail the build when it does not.
try:
    claude_datas, claude_binaries, claude_hiddenimports = collect_all(
        "claude_agent_sdk"
    )
except Exception:
    pass
else:
    datas += claude_datas
    binaries += claude_binaries
    hiddenimports += claude_hiddenimports
    datas += copy_metadata("claude-agent-sdk")

for executable_name in ("ffmpeg", "ffprobe"):
    executable = shutil.which(executable_name)
    if not executable:
        raise SystemExit(
            f"Required build tool was not found on PATH: {executable_name}.exe"
        )
    binaries.append((executable, "."))

icon_path = SOURCE_DIR / "storyflow_studio" / "assets" / "storyflow-logo.png"

a = Analysis(
    [str(PROJECT_DIR / "storyflow_launcher.py")],
    pathex=[str(SOURCE_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_DIR / "build-scripts" / "runtime_windows.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=str(icon_path),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
