"""Tests for desktop Controller close logic."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from desktop.controller import Controller


def _controller(monkeypatch, on_close="ask", running=0, settings=None):
    monkeypatch.setattr(
        "desktop.controller.load_settings",
        lambda: dict(settings) if settings else {"on_close": on_close},
    )
    saved = {}
    monkeypatch.setattr("desktop.controller.save_settings", lambda d: saved.update(d))
    c = Controller(port=8977)
    c.window = MagicMock()
    monkeypatch.setattr(c, "running_count", lambda: running)
    return c, saved


def _geometry_window(x=100, y=60, width=1000, height=700):
    win = MagicMock()
    win.x, win.y, win.width, win.height = x, y, width, height
    return win


def test_tray_pref_hides_and_cancels_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="tray")
    assert c.on_closing() is False
    c.window.hide.assert_called_once()


def test_exit_pref_allows_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="exit")
    assert c.on_closing() is True


def test_ask_no_browsers_allows_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="ask", running=0)
    assert c.on_closing() is True


def test_ask_with_browsers_shows_modal_and_cancels(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="ask", running=2)
    assert c.on_closing() is False
    c.window.evaluate_js.assert_called_once()


def test_choice_exit_remembers_and_forces_close(monkeypatch):
    c, saved = _controller(monkeypatch, on_close="ask", running=2)
    c.on_close_choice("exit", True)
    assert saved.get("on_close") == "exit"
    assert c._force_close is True
    c.window.destroy.assert_called_once()


def test_choice_tray_hides_without_remember(monkeypatch):
    c, saved = _controller(monkeypatch, on_close="ask", running=2)
    c.on_close_choice("tray", False)
    assert saved == {}
    c.window.hide.assert_called_once()


def test_force_close_bypasses_logic(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="tray")
    c._force_close = True
    assert c.on_closing() is True


# --- window-geometry persistence ---


def test_capture_saves_normal_bounds(monkeypatch):
    c, saved = _controller(monkeypatch)
    c.window = _geometry_window(x=120, y=80, width=1100, height=750)
    c.capture_window_geometry()
    assert saved["window"] == {
        "x": 120,
        "y": 80,
        "width": 1100,
        "height": 750,
        "maximized": False,
    }


def test_capture_maximized_keeps_stored_normal_bounds(monkeypatch):
    prior = {"x": 10, "y": 20, "width": 900, "height": 600}
    c, saved = _controller(
        monkeypatch, settings={"on_close": "ask", "window": dict(prior)}
    )
    # Maximized: the window itself reports full-screen bounds; they must not win.
    c.window = _geometry_window(x=0, y=0, width=1920, height=1040)
    c.on_win_maximized()
    c.capture_window_geometry()
    assert saved["window"] == {**prior, "maximized": True}


def test_capture_minimized_keeps_stored_bounds(monkeypatch):
    prior = {"x": 10, "y": 20, "width": 900, "height": 600, "maximized": False}
    c, saved = _controller(
        monkeypatch, settings={"on_close": "ask", "window": dict(prior)}
    )
    # Minimized windows are parked far off-screen by the OS.
    c.window = _geometry_window(x=-32000, y=-32000, width=160, height=28)
    c.on_win_minimized()
    c.capture_window_geometry()
    assert saved["window"] == prior


def test_minimized_from_maximized_still_remembers_maximized(monkeypatch):
    c, saved = _controller(monkeypatch)
    c.window = _geometry_window(x=-32000, y=-32000, width=160, height=28)
    c.on_win_maximized()
    c.on_win_minimized()
    c.capture_window_geometry()
    assert saved["window"] == {"maximized": True}


def test_restore_resumes_normal_capture(monkeypatch):
    c, saved = _controller(monkeypatch)
    c.window = _geometry_window(x=5, y=6, width=800, height=500)
    c.on_win_maximized()
    c.on_win_restored()
    c.capture_window_geometry()
    assert saved["window"] == {
        "x": 5,
        "y": 6,
        "width": 800,
        "height": 500,
        "maximized": False,
    }


def test_maximized_seeded_from_restored_settings(monkeypatch):
    # Window reopened maximized and closed without a state change in between:
    # the stored normal bounds must survive even if no 'maximized' event fired.
    prior = {"x": 10, "y": 20, "width": 900, "height": 600, "maximized": True}
    c, saved = _controller(
        monkeypatch, settings={"on_close": "ask", "window": dict(prior)}
    )
    c.window = _geometry_window(x=0, y=0, width=1920, height=1040)
    c.capture_window_geometry()
    assert saved["window"] == prior


def test_capture_garbage_bounds_not_persisted(monkeypatch):
    c, saved = _controller(monkeypatch)
    c.window = _geometry_window(x=0, y=0, width=1, height=1)
    c.capture_window_geometry()
    assert saved["window"] == {"maximized": False}


def test_capture_without_window_is_noop(monkeypatch):
    c, saved = _controller(monkeypatch)
    c.window = None
    c.capture_window_geometry()
    assert saved == {}


def test_on_closing_captures_geometry(monkeypatch):
    c, saved = _controller(monkeypatch, on_close="exit")
    c.window = _geometry_window(x=15, y=25, width=850, height=550)
    assert c.on_closing() is True
    assert saved["window"]["x"] == 15
    assert saved["window"]["maximized"] is False
