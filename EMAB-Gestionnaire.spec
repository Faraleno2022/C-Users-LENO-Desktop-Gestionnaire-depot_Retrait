# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import PySide6



a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt 6 utilise l'ICU native de Windows. Une ICU fournie par un autre
# outil du PATH (par exemple Poppler) expose des symboles différents et
# provoque "DLL load failed" au chargement de QtGui. Les éventuelles DLL
# fournies par le paquet Qt lui-même restent prioritaires et sont conservées.
qt_package = Path(PySide6.__file__).resolve().parent

def foreign_icu(binary):
    name = Path(binary[0]).name.lower()
    is_icu = name == "icuuc.dll" or (name.startswith("icudt") and name.endswith(".dll"))
    return is_icu and not Path(binary[1]).resolve().is_relative_to(qt_package)

a.binaries = [binary for binary in a.binaries if not foreign_icu(binary)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EMAB-Gestionnaire',
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
    icon=['assets\\logo_emab.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EMAB-Gestionnaire',
)
