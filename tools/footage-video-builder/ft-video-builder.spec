# -*- mode: python ; coding: utf-8 -*-

"""Canonical PyInstaller definition for Footage Video Builder."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)


PROJECT_DIR = Path(SPECPATH).resolve()
APP_NAME = "FootageVideoBuilder"
ASSETS_DIR = PROJECT_DIR / "assets"

datas = [(str(ASSETS_DIR), "assets")]
datas += collect_data_files("whisper")
for distribution in (
    "imageio",
    "imageio-ffmpeg",
    "moviepy",
    "openai-whisper",
    "transformers",
    "huggingface-hub",
    "scenedetect",
    "keyring",
):
    datas += copy_metadata(distribution)

hiddenimports = []
for package in (
    "whisper",
    "transformers.models.clip",
    "transformers.models.siglip",
    "transformers.models.siglip2",
    "keyring.backends",
):
    hiddenimports += collect_submodules(package)

icon_path = ASSETS_DIR / (
    "yt-vidbuilder.icns" if sys.platform == "darwin" else "yt-vidbuilder.ico"
)
icon = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(PROJECT_DIR / "main.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    icon=icon,
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

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.dawnwithgod.footage-video-builder",
    )
