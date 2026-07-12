"""Tests for desktop Controller close logic."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from desktop.controller import Controller


def _controller(monkeypatch, on_close="ask", running=0):
    monkeypatch.setattr("desktop.controller.load_settings", lambda: {"on_close": on_close})
    saved = {}
    monkeypatch.setattr("desktop.controller.save_settings", lambda d: saved.update(d))
    c = Controller(port=8977)
    c.window = MagicMock()
    monkeypatch.setattr(c, "running_count", lambda: running)
    return c, saved


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
