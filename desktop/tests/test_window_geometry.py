"""Tests for restoring the desktop window's remembered geometry."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from desktop import app as app_mod


def test_window_kwargs_defaults_when_nothing_saved():
    assert app_mod._window_kwargs({"on_close": "ask"}) == {"width": 1280, "height": 800}


def test_window_kwargs_uses_saved_bounds():
    s = {"window": {"x": 40, "y": 30, "width": 1000, "height": 700, "maximized": False}}
    assert app_mod._window_kwargs(s) == {"x": 40, "y": 30, "width": 1000, "height": 700}


def test_window_kwargs_maximized_with_bounds():
    s = {"window": {"x": 40, "y": 30, "width": 1000, "height": 700, "maximized": True}}
    kwargs = app_mod._window_kwargs(s)
    assert kwargs["maximized"] is True
    assert kwargs["width"] == 1000  # restore-down size


def test_window_kwargs_maximized_without_bounds_uses_default_size():
    kwargs = app_mod._window_kwargs({"window": {"maximized": True}})
    assert kwargs == {"width": 1280, "height": 800, "maximized": True}


def _screen(x=0, y=0, width=1920, height=1080):
    return SimpleNamespace(x=x, y=y, width=width, height=height)


def _window(x, y, width, height):
    win = MagicMock()
    win.x, win.y, win.width, win.height = x, y, width, height
    return win


def test_keep_window_visible_leaves_onscreen_window_alone(monkeypatch):
    monkeypatch.setattr(app_mod.webview, "screens", [_screen()], raising=False)
    win = _window(100, 100, 800, 600)
    app_mod._keep_window_visible(win)
    win.move.assert_not_called()


def test_keep_window_visible_accepts_secondary_monitor(monkeypatch):
    monkeypatch.setattr(
        app_mod.webview, "screens", [_screen(), _screen(x=1920)], raising=False
    )
    win = _window(2200, 100, 800, 600)
    app_mod._keep_window_visible(win)
    win.move.assert_not_called()


def test_keep_window_visible_recenters_lost_window(monkeypatch):
    monkeypatch.setattr(app_mod.webview, "screens", [_screen()], raising=False)
    win = _window(-5000, 100, 800, 600)  # was on a monitor that is gone now
    app_mod._keep_window_visible(win)
    win.move.assert_called_once_with((1920 - 800) // 2, (1080 - 600) // 2)


def test_keep_window_visible_survives_screen_query_failure(monkeypatch):
    class Boom:
        def __iter__(self):
            raise RuntimeError("no gui")

    monkeypatch.setattr(app_mod.webview, "screens", Boom(), raising=False)
    win = _window(100, 100, 800, 600)
    app_mod._keep_window_visible(win)  # must not raise
    win.move.assert_not_called()
