"""Track CloakBrowser Chromium kernel download/readiness state for /api/health.

The kernel is downloaded on first run by cloakbrowser.ensure_binary() (blocking).
This tracker is updated from a background thread so the health endpoint can report
downloading / ready / error without blocking startup.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Literal

logger = logging.getLogger("cloakbrowser.manager.binary")

State = Literal["downloading", "ready", "error"]


class BinaryStatusTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: State = "downloading"
        self._version: str | None = None
        self._error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "version": self._version, "error": self._error}

    def mark_downloading(self) -> None:
        with self._lock:
            self._state = "downloading"
            self._error = None

    def mark_ready(self, version: str | None) -> None:
        with self._lock:
            self._state = "ready"
            self._version = version
            self._error = None

    def mark_error(self, error: str) -> None:
        with self._lock:
            self._state = "error"
            self._error = error


def run_ensure_binary(
    tracker: BinaryStatusTracker,
    ensure_fn: Callable[[], object],
    version_fn: Callable[[], str | None],
) -> None:
    """Ensure the kernel is present, updating the tracker. Blocking — run in a thread."""
    tracker.mark_downloading()
    try:
        ensure_fn()
    except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
        logger.error("Kernel ensure_binary failed: %s", exc)
        tracker.mark_error(str(exc))
        return
    try:
        version = version_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kernel version lookup failed: %s", exc)
        version = None
    tracker.mark_ready(version)
    logger.info("Kernel ready (version=%s)", version)


# Module-level singleton — shared by main.py (health endpoint, lifespan)
# and browser_manager (launch gating).
tracker = BinaryStatusTracker()


def _ensure_kernel() -> None:
    from cloakbrowser.download import ensure_binary

    ensure_binary()


def _kernel_version() -> str | None:
    from cloakbrowser.config import CHROMIUM_VERSION

    return CHROMIUM_VERSION


def start_background_ensure() -> threading.Thread:
    """Kick off the (blocking) kernel download in a daemon thread."""
    thread = threading.Thread(
        target=run_ensure_binary,
        args=(tracker, _ensure_kernel, _kernel_version),
        name="ensure-binary",
        daemon=True,
    )
    thread.start()
    return thread
