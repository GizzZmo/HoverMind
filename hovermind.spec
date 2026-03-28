# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for HoverMind – Windows standalone executable.
#
# Usage
# -----
# Install PyInstaller (pip install pyinstaller) then run:
#
#   pyinstaller hovermind.spec
#
# The resulting one-file executable is placed in dist/HoverMind.exe.
# No Python installation is required on the target machine.

import sys
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

block_cipher = None

a = Analysis(
    ["hovermind.py"],
    pathex=[],
    binaries=[],
    datas=[
        (".env.example", "."),
    ],
    hiddenimports=[
        "PIL._tkinter_finder",
        "google.genai",
        "google.genai.types",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HoverMind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window — runs silently in the tray
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows-specific: declare DPI awareness so physical-pixel capture works.
    uac_admin=False,
    manifest="""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">
        PerMonitorV2
      </dpiAwareness>
    </windowsSettings>
  </application>
</assembly>""",
)
