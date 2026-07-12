"""Verify the desktop shell anchors DATA_DIR to the app root."""
from __future__ import annotations

from pathlib import Path

from desktop import app as app_mod


def test_app_root_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "CloakBrowserManager" / "CloakBrowserManager.exe"
    monkeypatch.setattr(app_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_mod.sys, "executable", str(exe))
    assert app_mod.app_root() == exe.resolve().parent


def test_app_root_source(monkeypatch):
    monkeypatch.setattr(app_mod.sys, "frozen", False, raising=False)
    # repo root: the folder containing desktop/
    assert app_mod.app_root() == Path(app_mod.__file__).resolve().parent.parent


def test_env_defaults_point_data_dir_at_app_root(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("USE_VNC", raising=False)
    app_mod._apply_env_defaults()
    import os

    assert os.environ["USE_VNC"] == "0"
    assert os.environ["DATA_DIR"] == str(app_mod.app_root())


def test_env_defaults_respect_explicit_overrides(monkeypatch):
    monkeypatch.setenv("DATA_DIR", r"E:\custom-data")
    monkeypatch.setenv("USE_VNC", "1")
    app_mod._apply_env_defaults()
    import os

    assert os.environ["DATA_DIR"] == r"E:\custom-data"
    assert os.environ["USE_VNC"] == "1"


def test_data_dir_env_reaches_backend_config(monkeypatch, tmp_path):
    from backend.config import get_data_dir

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert get_data_dir() == tmp_path
