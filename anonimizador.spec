# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para generar un ejecutable de escritorio unico
# (--onefile, sin consola). Generar el binario de Windows requiere ejecutar
# PyInstaller en una maquina Windows real (no permite cross-compilar);
# ver build_windows.bat / build_linux.sh.

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["dicomanonymizer"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AnonimizadorDICOM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
