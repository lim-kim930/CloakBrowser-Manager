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
