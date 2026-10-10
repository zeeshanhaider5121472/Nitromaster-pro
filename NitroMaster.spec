# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: NitroMasterPro.exe (onefile, windowed, x64)."""
import sys

block_cipher = None

a = Analysis(
    ['nitromaster/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pythonnet', 'clr', 'LibreHardwareMonitor.Hardware',
        'wmi', 'win32com.client', 'win32pdh', 'win32service', 'winreg',
        'pynvml', 'psutil', 'cpuinfo',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc_data'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NitroMasterPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x64',
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
