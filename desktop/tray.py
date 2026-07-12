"""System-tray icon for the desktop client."""
from __future__ import annotations

import logging

import pystray
from PIL import Image, ImageDraw

from desktop.settings import save_settings

logger = logging.getLogger("cloakbrowser.desktop.tray")


def _placeholder_icon() -> Image.Image:
    """A simple 64×64 icon. Replace desktop/assets/icon.png for a real one."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(37, 99, 235, 255))
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
    return img


def create_tray(controller) -> "pystray.Icon":
    def on_open(icon, item):
        if controller.window is not None:
            controller.window.show()

    def on_reset(icon, item):
        controller.settings["on_close"] = "ask"
        save_settings(controller.settings)

    def on_quit(icon, item):
        controller._force_close = True
        if controller.window is not None:
            controller.window.destroy()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Manager", on_open, default=True),
        pystray.MenuItem("Reset close behavior", on_reset),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("cloakbrowser", _placeholder_icon(), "CloakBrowser Manager", menu)
