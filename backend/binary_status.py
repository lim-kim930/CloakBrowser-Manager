"""Kernel library status for /api/health + on-demand download runner.

The library state is derived from the kernels table; the only mutable piece
is the download tracker (user-triggered, one at a time).
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Callable, Literal

from . import database as db

logger = logging.getLogger("cloakbrowser.manager.binary")

LibraryState = Literal["none", "downloading", "ready", "error"]
DownloadState = Literal["idle", "downloading", "ready", "error"]


class DownloadTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: DownloadState = "idle"
        self._error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "error": self._error}

    def _set(self, state: DownloadState, error: str | None) -> None:
        with self._lock:
            self._state = state
            self._error = error

    def start(self) -> bool:
        """Kick off the recommended-version download in a daemon thread.

        Returns False if a download is already running.
        """
        with self._lock:
            if self._state == "downloading":
                return False
            self._state = "downloading"
            self._error = None
        threading.Thread(
            target=run_download, args=(self, _ensure_recommended),
            name="kernel-download", daemon=True,
        ).start()
        return True


download = DownloadTracker()


def _ensure_recommended() -> str:
    from cloakbrowser.download import ensure_binary

    return str(ensure_binary())


def run_download(tracker: DownloadTracker, ensure_fn: Callable[[], str]) -> None:
    """Download the recommended kernel and register it. Blocking — run in a thread."""
    tracker._set("downloading", None)
    try:
        exe_path = ensure_fn()
    except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
        logger.error("Kernel download failed: %s", exc)
        tracker._set("error", str(exc))
        return
    version = _version_from_exe_path(exe_path)
    if version is None:
        tracker._set("error", f"Downloaded kernel has unexpected path layout: {exe_path}")
        return
    if not db.get_kernel_by_version(version):
        db.create_kernel(version, "downloaded")
    tracker._set("ready", None)
    logger.info("Kernel %s downloaded and registered", version)


def _version_from_exe_path(exe_path: str) -> str | None:
    """Extract the version from .../chromium-{version}[...]/<exe>."""
    for part in reversed(Path(exe_path).parts):
        m = re.fullmatch(r"chromium-(\d+(?:\.\d+){2,4})(?:-pro)?", part)
        if m:
            return m.group(1)
    return None


def library_snapshot() -> dict:
    """State of the kernel library, for /api/health."""
    dl = download.snapshot()
    if dl["state"] == "downloading":
        return {"state": "downloading", "version": None, "error": None}
    kernels = db.list_kernels()
    if kernels:
        default = db.get_default_kernel()
        version = default["version"] if default else kernels[0]["version"]
        return {"state": "ready", "version": version, "error": None}
    if dl["state"] == "error":
        return {"state": "error", "version": None, "error": dl["error"]}
    return {"state": "none", "version": None, "error": None}
