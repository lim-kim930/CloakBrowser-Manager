"""Owns the desktop window lifecycle and close-behavior decisions."""
from __future__ import annotations

import json
import logging
import urllib.request

from desktop.server import ServerHandle
from desktop.settings import load_settings, sanitize_window, save_settings

logger = logging.getLogger("cloakbrowser.desktop.controller")


class Controller:
    def __init__(self, port: int) -> None:
        self.port = port
        self.window = None  # set by app.py after create_window
        self.server = ServerHandle()
        self.settings = load_settings()
        self._force_close = False
        # Window-state flags fed by pywebview events (wired in app.py). Geometry
        # itself is read from the window only at close time: the moved/resized
        # events fire on unordered threads during a maximize, so tracking
        # "last normal bounds" through them would race. Seed maximized from the
        # restored state so closing a still-maximized window keeps its normal
        # bounds (the 'maximized' event may not fire on startup).
        self._win_maximized = bool((self.settings.get("window") or {}).get("maximized"))
        self._win_minimized = False

    def on_win_maximized(self) -> None:
        self._win_maximized = True
        self._win_minimized = False

    def on_win_minimized(self) -> None:
        # Keep _win_maximized: a window minimized from maximized returns to
        # maximized on restore, so that is the state worth remembering.
        self._win_minimized = True

    def on_win_restored(self) -> None:
        self._win_maximized = False
        self._win_minimized = False

    def capture_window_geometry(self) -> None:
        """Persist current window bounds so the next launch can restore them."""
        if self.window is None:
            return
        try:
            win = dict(self.settings.get("window") or {})
            if not self._win_maximized and not self._win_minimized:
                bounds = sanitize_window(
                    {
                        "x": int(self.window.x),
                        "y": int(self.window.y),
                        "width": int(self.window.width),
                        "height": int(self.window.height),
                    }
                )
                if bounds:
                    win.update(bounds)
            # Maximized: the properties report the maximized bounds, so keep the
            # stored normal bounds. Minimized: the OS parks the window off-screen
            # (-32000), so keep the stored bounds too.
            win["maximized"] = self._win_maximized
            self.settings["window"] = win
            save_settings(self.settings)
        except Exception as exc:  # noqa: BLE001 - never block closing on this
            logger.warning("could not save window geometry: %s", exc)

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
        # Every close path funnels through here (X button, tray Quit and the
        # close-modal Exit both destroy() which fires 'closing' too), so this is
        # the one spot geometry must be captured.
        self.capture_window_geometry()
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
