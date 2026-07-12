"""Runtime configuration: display mode and path resolution.

The single axis is *whether VNC is used*, never the operating system.
Resolved fresh on each call; callers cache at startup if needed.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def use_vnc() -> bool:
    """Return True if profiles should render through VNC.

    USE_VNC=1/true/... → VNC; USE_VNC=0/false/... → native.
    Unset or unrecognized → auto-detect: Xvnc on PATH ⇒ VNC.
    """
    raw = os.environ.get("USE_VNC")
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUTHY:
            return True
        if val in _FALSY:
            return False
    return shutil.which("Xvnc") is not None


def display_mode() -> str:
    """"vnc" or "native" — the string form exposed to the frontend."""
    return "vnc" if use_vnc() else "native"


def get_data_dir() -> Path:
    """Resolve the data directory.

    DATA_DIR env wins. Else Windows → %APPDATA%\\CloakBrowser-Manager,
    other platforms → /data (Docker default, unchanged).
    """
    raw = os.environ.get("DATA_DIR")
    if raw:
        return Path(raw)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "CloakBrowser-Manager"
    return Path("/data")


# Env var honored by the cloakbrowser package: overrides where the kernel
# (browser binary) cache lives. Read fresh by the package on every resolve,
# so updating os.environ at runtime re-points subsequent downloads/launches.
KERNEL_DIR_ENV = "CLOAKBROWSER_CACHE_DIR"


def default_kernel_dir() -> Path:
    """The cloakbrowser package's documented default cache location."""
    return Path.home() / ".cloakbrowser"


def effective_kernel_dir() -> Path:
    """Where the kernel is stored/downloaded right now (env override or default)."""
    raw = os.environ.get(KERNEL_DIR_ENV)
    return Path(raw) if raw else default_kernel_dir()


def frontend_dir() -> Path:
    """Locate the built React SPA, in both source and PyInstaller-frozen runs."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "frontend" / "dist"
    return Path(__file__).parent.parent / "frontend" / "dist"
