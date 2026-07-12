"""Desktop client entry point: uvicorn + pywebview window + tray."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from pathlib import Path

import webview

from desktop import server, tray
from desktop.api_bridge import ApiBridge
from desktop.controller import Controller

logger = logging.getLogger("cloakbrowser.desktop")

_DEFAULT_SIZE = (1280, 800)


def app_root() -> Path:
    """The client's install root: the exe's folder when frozen, repo root from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _window_kwargs(settings: dict) -> dict:
    """Geometry kwargs for create_window from the remembered window state.

    No remembered state → default size, centered by the OS (first-run behavior).
    """
    kwargs: dict = {"width": _DEFAULT_SIZE[0], "height": _DEFAULT_SIZE[1]}
    win = settings.get("window") or {}
    if {"x", "y", "width", "height"} <= win.keys():
        kwargs.update(x=win["x"], y=win["y"], width=win["width"], height=win["height"])
    if win.get("maximized"):
        kwargs["maximized"] = True
    return kwargs


def _keep_window_visible(window) -> None:
    """Move a remembered window back on-screen if its monitor is gone."""
    try:
        screens = webview.screens
        x, y, width, height = window.x, window.y, window.width, window.height
        for s in screens:
            overlap_w = min(x + width, s.x + s.width) - max(x, s.x)
            overlap_h = min(y + height, s.y + s.height) - max(y, s.y)
            # Enough of the title bar to see and grab the window
            if overlap_w >= 100 and overlap_h >= 50:
                return
        primary = screens[0]
        window.move(
            primary.x + max((primary.width - width) // 2, 0),
            primary.y + max((primary.height - height) // 2, 0),
        )
    except Exception as exc:  # noqa: BLE001 - cosmetic safeguard only
        logger.warning("screen-visibility check failed: %s", exc)


def _apply_env_defaults() -> None:
    """Set native-mode defaults; explicit env vars always win (setdefault)."""
    os.environ.setdefault("USE_VNC", "0")
    # Keep data (profiles, DB, settings.json) next to the client instead of APPDATA.
    os.environ.setdefault("DATA_DIR", str(app_root()))


def _message_box(text: str, title: str = "CloakBrowser Manager") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        print(f"{title}: {text}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    _apply_env_defaults()
    port = int(os.environ.get("CLOAK_PORT", "8977"))

    if server.port_in_use(port):
        _message_box("CloakBrowser Manager is already running.")
        return

    controller = Controller(port)
    controller.server.start(port)

    if not server.wait_for_server(f"http://127.0.0.1:{port}/api/status", timeout=30):
        _message_box("Failed to start the backend server.")
        controller.server.stop()
        return

    bridge = ApiBridge(controller)
    window = webview.create_window(
        "CloakBrowser Manager",
        f"http://127.0.0.1:{port}",
        js_api=bridge,
        **_window_kwargs(controller.settings),
    )
    controller.window = window
    window.events.closing += controller.on_closing
    window.events.maximized += controller.on_win_maximized
    window.events.minimized += controller.on_win_minimized
    window.events.restored += controller.on_win_restored
    if controller.settings.get("window"):
        window.events.shown += lambda: _keep_window_visible(window)

    tray_icon = tray.create_tray(controller)
    threading.Thread(target=tray_icon.run, daemon=True, name="tray").start()

    webview.start()  # blocks until the window is destroyed

    # Window closed → tear down tray and backend (lifespan shutdown closes browsers)
    try:
        tray_icon.stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tray stop failed: %s", exc)
    controller.server.stop(timeout=10)


if __name__ == "__main__":
    main()
