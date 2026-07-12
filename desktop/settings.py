"""Persist the desktop client's preferences (close behavior, window geometry)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config import get_data_dir

logger = logging.getLogger("cloakbrowser.desktop.settings")

_DEFAULTS = {"on_close": "ask"}

# A remembered window smaller than this is unusable; treat it as corrupt.
MIN_WINDOW_SIZE = (400, 300)


def _path() -> Path:
    return get_data_dir() / "settings.json"


def sanitize_window(raw: object) -> dict | None:
    """Return a validated window-geometry dict, or None if unusable.

    Shape: {x, y, width, height: int, maximized: bool} — bounds are all-or-nothing
    so a restore never mixes a saved position with a default size.
    """
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    bounds = [raw.get(k) for k in ("x", "y", "width", "height")]
    if (
        all(type(v) is int for v in bounds)  # bool is an int subclass; exclude it
        and bounds[2] >= MIN_WINDOW_SIZE[0]
        and bounds[3] >= MIN_WINDOW_SIZE[1]
        and all(abs(v) < 100_000 for v in bounds)
    ):
        out.update(zip(("x", "y", "width", "height"), bounds))
    if isinstance(raw.get("maximized"), bool):
        out["maximized"] = raw["maximized"]
    return out or None


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
        window = sanitize_window(merged.get("window"))
        if window is not None:
            merged["window"] = window
        else:
            merged.pop("window", None)
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
