# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('D:\\yt-src\\TOOL-YOUTUBE\\footage-finder-ai\\assets\\icons\\app_icon.png', 'assets\\icons')]
hiddenimports = ['sentencepiece', 'torch']
datas += collect_data_files('transformers')
hiddenimports += collect_submodules('transformers.models.siglip')
hiddenimports += collect_submodules('transformers.models.auto')


a = Analysis(
    ['D:\\yt-src\\TOOL-YOUTUBE\\stock-footage-fetcher\\stock_footage_app.py'],
    pathex=['D:\\yt-src\\TOOL-YOUTUBE\\stock-footage-fetcher'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DawnWithGod-FootageFinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DawnWithGod-FootageFinder',
)
