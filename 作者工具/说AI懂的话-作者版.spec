# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['webview.platforms.cocoa']
hiddenimports += collect_submodules('webview')


a = Analysis(
    ['PromptBridge.py'],
    pathex=[],
    binaries=[],
    datas=[('license.py', '.'), ('reporter.py', '.'), ('/Users/mac/Library/Python/3.9/lib/python/site-packages/webview/js', 'webview/js')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', '_pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='说AI懂的话-作者版',
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
    name='说AI懂的话-作者版',
)
app = BUNDLE(
    coll,
    name='说AI懂的话-作者版.app',
    icon=None,
    bundle_identifier=None,
)
