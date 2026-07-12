"""JS-exposed API surface for the pywebview window."""
from __future__ import annotations

import logging

import webview

from desktop.controller import Controller

logger = logging.getLogger("cloakbrowser.desktop.bridge")


class ApiBridge:
    def __init__(self, controller: Controller) -> None:
        self._c = controller

    def on_close_choice(self, choice: str, remember: bool) -> None:
        self._c.on_close_choice(choice, remember)

    def pick_folder(self) -> str | None:
        """Open a native folder-picker dialog; return the chosen path or None."""
        window = self._c.window
        if window is None:
            return None
        try:
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as exc:  # noqa: BLE001 — never crash the JS bridge
            logger.warning("folder dialog failed: %s", exc)
            return None
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else str(result)
