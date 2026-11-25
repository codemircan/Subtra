# -*- mode: python ; coding: utf-8 -*-
"""Subtra PyInstaller spec.

Kullanim:
    py -m PyInstaller Subtra.spec --noconfirm --clean

Notlar:
  * FFmpeg exe'ye GOMULMEZ (uygulama gerekirse otomatik indirir) ama
    `ffmpeg/` klasoru dist yaninda bulunursa oncelikli olarak kullanilir.
  * `models/` klasoru de gomulmez; ilk kullanimda indirilir.
"""

from pathlib import Path

BLOCK_CIPHER = None
PROJECT = Path(SPECPATH)

datas = []

# Simge varsa ekle
icon_path = PROJECT / "assets" / "app.ico"
icon = str(icon_path) if icon_path.exists() else None

hiddenimports = [
    "tokenizers",
    "sentencepiece",
    "ctranslate2",
    "faster_whisper",
    "psutil",
    "requests",
    "onnxruntime",
    "av",
    "numpy",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Subtra",
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
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Subtra",
)
