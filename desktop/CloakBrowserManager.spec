# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller desktop/CloakBrowserManager.spec  (run from repo root)
import os

from PyInstaller.utils.hooks import collect_all

# PyInstaller resolves relative paths in a spec relative to the spec's own
# directory (here: desktop/), so anchor repo-root-relative inputs to ROOT.
ROOT = os.path.dirname(SPECPATH)  # SPECPATH == <repo>/desktop -> ROOT == <repo>

datas = [(os.path.join(ROOT, "frontend", "dist"), "frontend/dist")]
binaries = []
hiddenimports = ["backend.main", "desktop.app"]

# Bundle cloakbrowser + webview + pystray data/backends
for pkg in ("cloakbrowser", "webview", "pystray"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "desktop", "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
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
    [],
    exclude_binaries=True,
    name="CloakBrowserManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app, no console
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="CloakBrowserManager",
)
