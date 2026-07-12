"""Owns the desktop window lifecycle and close-behavior decisions."""
from __future__ import annotations

import json
import logging
import urllib.request

from desktop.server import ServerHandle
from desktop.settings import load_settings, save_settings

logger = logging.getLogger("cloakbrowser.desktop.controller")


class Controller:
    def __init__(self, port: int) -> None:
        self.port = port
        self.window = None  # set by app.py after create_window
        self.server = ServerHandle()
        self.settings = load_settings()
        self._force_close = False

    def running_count(self) -> int:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/status", timeout=2
            ) as r:
                return int(json.loads(r.read()).get("running_count", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("running_count query failed: %s", exc)
            return 0

    def on_closing(self) -> bool:
        """pywebview 'closing' handler. Return True to allow close, False to cancel."""
        if self._force_close:
            return True
        choice = self.settings.get("on_close", "ask")
        if choice == "tray":
            self.window.hide()
            return False
        if choice == "exit":
            return True
        # "ask"
        if self.running_count() == 0:
            return True
        self.window.evaluate_js("window.__cbShowCloseModal && window.__cbShowCloseModal()")
        return False

    def on_close_choice(self, choice: str, remember: bool) -> None:
        """Called from the frontend (via ApiBridge) after the modal is answered."""
        if remember and choice in ("exit", "tray"):
            self.settings["on_close"] = choice
            save_settings(self.settings)
        if choice == "tray":
            self.window.hide()
        elif choice == "exit":
            self._force_close = True
            self.window.destroy()
        # "cancel": do nothing
