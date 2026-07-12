"""Desktop client entry point: uvicorn + pywebview window + tray."""
from __future__ import annotations

import ctypes
import logging
import os
import threading

import webview

from desktop import server, tray
from desktop.api_bridge import ApiBridge
from desktop.controller import Controller

logger = logging.getLogger("cloakbrowser.desktop")


def _message_box(text: str, title: str = "CloakBrowser Manager") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        print(f"{title}: {text}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    # Native mode unless the user explicitly overrode it.
    os.environ.setdefault("USE_VNC", "0")
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
        width=1280,
        height=800,
    )
    controller.window = window
    window.events.closing += controller.on_closing

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
