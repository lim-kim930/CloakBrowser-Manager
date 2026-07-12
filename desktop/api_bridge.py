"""JS-exposed API surface for the pywebview window."""
from __future__ import annotations

from desktop.controller import Controller


class ApiBridge:
    def __init__(self, controller: Controller) -> None:
        self._c = controller

    def on_close_choice(self, choice: str, remember: bool) -> None:
        self._c.on_close_choice(choice, remember)
