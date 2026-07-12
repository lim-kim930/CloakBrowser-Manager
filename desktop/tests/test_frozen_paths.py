"""Verify frontend_dir resolves under a simulated PyInstaller freeze."""
from __future__ import annotations

import sys
from pathlib import Path

from backend import config


def test_frontend_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(tmp_path), raising=False)
    d = config.frontend_dir()
    assert d == Path(str(tmp_path)) / "frontend" / "dist"


def test_frontend_dir_source(monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    d = config.frontend_dir()
    assert d.parts[-2:] == ("frontend", "dist")
