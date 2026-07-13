"""Build the PyInstaller sidecar and install it where Tauri expects it.

Usage (from repo root):
    backend/.venv/Scripts/python.exe backend/build.py

Produces backend/dist/server(.exe) and copies it to
frontend/src-tauri/bin/server-<target-triple>(.exe) for Tauri's externalBin.

The CloakBrowser Chromium kernel is NOT bundled (BINARY-LICENSE.md forbids
redistribution) — the frozen backend downloads it on first run.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TAURI_BIN = REPO_ROOT / "frontend" / "src-tauri" / "bin"


def target_triple() -> str:
    """Host target triple — ask rustc, fall back to platform-derived."""
    try:
        out = subprocess.run(
            ["rustc", "-Vv"], capture_output=True, text=True, check=True
        ).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split()[1]
    except (OSError, subprocess.CalledProcessError):
        pass
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[
        platform.machine().lower()
    ]
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def crypto_collect_args() -> list[str]:
    """Collect whichever signature-verification lib cloakbrowser installed —
    Ed25519 verification of the kernel download must work when frozen."""
    args: list[str] = []
    for pkg in ("cryptography", "nacl"):
        if importlib.util.find_spec(pkg) is not None:
            args += ["--collect-all", pkg]
    return args


def main() -> None:
    ext = ".exe" if sys.platform == "win32" else ""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        # onefile matches Tauri's single-file sidecar model. Escape hatch if
        # cold start or AV false-positives bite: switch to --onedir and bundle
        # the directory as Tauri resources instead of externalBin.
        "--onefile",
        "--name", "server",
        "--distpath", str(BACKEND / "dist"),
        "--workpath", str(BACKEND / "build"),
        "--specpath", str(BACKEND),
        "--paths", str(REPO_ROOT),
        "--collect-all", "cloakbrowser",   # geoip data + pinned signing pubkey
        "--collect-all", "playwright",     # node driver — the easiest miss
        "--collect-all", "uvicorn",        # uvicorn.logging + loop/proto submodules
        "--collect-all", "websockets",
        *crypto_collect_args(),
        str(BACKEND / "sidecar_entry.py"),
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

    built = BACKEND / "dist" / f"server{ext}"
    if not built.exists():
        sys.exit(f"PyInstaller did not produce {built}")

    TAURI_BIN.mkdir(parents=True, exist_ok=True)
    dest = TAURI_BIN / f"server-{target_triple()}{ext}"
    shutil.copy2(built, dest)
    print(f"sidecar installed: {dest}")


if __name__ == "__main__":
    main()
