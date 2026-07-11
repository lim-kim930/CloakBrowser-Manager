"""Tests for runtime mode + path resolution."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend import config


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("off", False), ("", None),
])
def test_use_vnc_explicit_env(monkeypatch, raw, expected):
    monkeypatch.setenv("USE_VNC", raw)
    if expected is None:
        # empty string falls through to auto-detect; force which() to None
        monkeypatch.setattr(config.shutil, "which", lambda _: None)
        assert config.use_vnc() is False
    else:
        assert config.use_vnc() is expected


def test_use_vnc_autodetect_xvnc_present(monkeypatch):
    monkeypatch.delenv("USE_VNC", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/Xvnc")
    assert config.use_vnc() is True


def test_use_vnc_autodetect_xvnc_absent(monkeypatch):
    monkeypatch.delenv("USE_VNC", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    assert config.use_vnc() is False


def test_display_mode_strings(monkeypatch):
    monkeypatch.setenv("USE_VNC", "1")
    assert config.display_mode() == "vnc"
    monkeypatch.setenv("USE_VNC", "0")
    assert config.display_mode() == "native"


def test_get_data_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert config.get_data_dir() == tmp_path


def test_get_data_dir_windows_default(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    assert config.get_data_dir() == Path(r"C:\Users\me\AppData\Roaming") / "CloakBrowser-Manager"


def test_get_data_dir_posix_default(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    assert config.get_data_dir() == Path("/data")


def test_frontend_dir_not_frozen(monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    d = config.frontend_dir()
    assert d.parts[-2:] == ("frontend", "dist")
