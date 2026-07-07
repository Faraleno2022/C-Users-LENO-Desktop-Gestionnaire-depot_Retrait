# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

# Rend les paquets locaux (web, core, sync) importables pendant l'analyse :
# sans cela, collect_data_files('web') est ignoré et les templates manquent
# dans l'exe (TemplateDoesNotExist: web/login.html au premier écran).
sys.path.insert(0, SPECPATH)

datas = [('staticfiles', 'staticfiles')]
hiddenimports = ['waitress', 'dj_database_url', 'dotenv', 'updater']
datas += collect_data_files('web')
datas += collect_data_files('django')
datas += collect_data_files('rest_framework')
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('sync')
hiddenimports += collect_submodules('web')
hiddenimports += collect_submodules('django')
hiddenimports += collect_submodules('rest_framework')
hiddenimports += collect_submodules('whitenoise')


a = Analysis(
    ['console_web.py'],
    pathex=['.'],
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
    name='EMAB-Console-Web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['..\\assets\\logo_emab.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EMAB-Console-Web',
)
