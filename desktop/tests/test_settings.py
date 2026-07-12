"""Tests for desktop settings persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from desktop import settings


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    return tmp_path


def test_load_defaults_when_missing(data_dir):
    assert settings.load_settings() == {"on_close": "ask"}


def test_save_then_load_roundtrip(data_dir: Path):
    settings.save_settings({"on_close": "tray"})
    assert (data_dir / "settings.json").exists()
    assert settings.load_settings()["on_close"] == "tray"


def test_corrupt_file_falls_back_to_default(data_dir: Path):
    (data_dir / "settings.json").write_text("{not json", encoding="utf-8")
    assert settings.load_settings() == {"on_close": "ask"}


def test_window_geometry_roundtrip(data_dir: Path):
    settings.save_settings(
        {"on_close": "ask", "window": {"x": 100, "y": 60, "width": 1000, "height": 700}}
    )
    loaded = settings.load_settings()
    assert loaded["window"] == {"x": 100, "y": 60, "width": 1000, "height": 700}


def test_window_maximized_kept_without_bounds(data_dir: Path):
    settings.save_settings({"on_close": "ask", "window": {"maximized": True}})
    assert settings.load_settings()["window"] == {"maximized": True}


def test_undersized_window_bounds_are_dropped(data_dir: Path):
    settings.save_settings(
        {"on_close": "ask", "window": {"x": 0, "y": 0, "width": 50, "height": 40}}
    )
    assert "window" not in settings.load_settings()


def test_partial_window_bounds_are_dropped(data_dir: Path):
    settings.save_settings({"on_close": "ask", "window": {"x": 100, "y": 60}})
    assert "window" not in settings.load_settings()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "nope",
        {"x": 1.5, "y": 0, "width": 1000, "height": 700},  # non-int
        {"x": True, "y": 0, "width": 1000, "height": 700},  # bool is not a real int here
        {"x": 0, "y": 0, "width": 1000, "height": 999999},  # absurd
    ],
)
def test_sanitize_window_rejects_bad_input(raw):
    assert settings.sanitize_window(raw) is None


def test_sanitize_window_negative_position_allowed():
    # A window on a secondary monitor to the left legitimately has x < 0.
    out = settings.sanitize_window({"x": -1400, "y": 200, "width": 1000, "height": 700})
    assert out == {"x": -1400, "y": 200, "width": 1000, "height": 700}
