"""Persist the desktop client's close-behavior preference."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config import get_data_dir

logger = logging.getLogger("cloakbrowser.desktop.settings")

_DEFAULTS = {"on_close": "ask"}


def _path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> dict:
    """Return persisted settings, falling back to defaults on any problem."""
    p = _path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULTS)
        merged = dict(_DEFAULTS)
        merged.update(data)
        if merged.get("on_close") not in ("ask", "exit", "tray"):
            merged["on_close"] = "ask"
        return merged
    except FileNotFoundError:
        return dict(_DEFAULTS)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("settings.json unreadable (%s); using defaults", exc)
        return dict(_DEFAULTS)


def save_settings(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
