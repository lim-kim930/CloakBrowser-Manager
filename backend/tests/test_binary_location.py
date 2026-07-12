"""Tests for the user-configurable kernel storage location."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import main
from backend.config import KERNEL_DIR_ENV, default_kernel_dir, effective_kernel_dir


# ── config helpers ───────────────────────────────────────────────────────────


def test_effective_kernel_dir_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    assert effective_kernel_dir() == default_kernel_dir()
    assert default_kernel_dir() == Path.home() / ".cloakbrowser"


def test_effective_kernel_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(KERNEL_DIR_ENV, str(tmp_path))
    assert effective_kernel_dir() == tmp_path


# ── startup application of the persisted setting ────────────────────────────


def test_persisted_kernel_dir_exported_at_startup(tmp_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    db.set_setting(main.KERNEL_DIR_SETTING, r"D:\kernels")
    main._apply_persisted_kernel_dir()
    assert effective_kernel_dir() == Path(r"D:\kernels")


def test_explicit_env_wins_over_persisted_setting(tmp_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(KERNEL_DIR_ENV, r"D:\from-env")
    db.set_setting(main.KERNEL_DIR_SETTING, r"D:\from-settings")
    main._apply_persisted_kernel_dir()
    assert effective_kernel_dir() == Path(r"D:\from-env")


# ── /api/binary/location endpoints ───────────────────────────────────────────


def test_get_location_default(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    resp = app_client.get("/api/binary/location")
    assert resp.status_code == 200
    data = resp.json()
    assert data["kernel_dir"] == str(default_kernel_dir())
    assert data["default_kernel_dir"] == str(default_kernel_dir())
    assert data["is_default"] is True


def test_put_location_persists_and_repoints(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    monkeypatch.setattr(main, "use_vnc", lambda: True)  # VNC re-checks via start()
    reset = MagicMock()
    start = MagicMock()
    monkeypatch.setattr(main.binary_mgr, "reset", reset)
    monkeypatch.setattr(main.binary_mgr, "start", start)

    target = tmp_path / "my-kernel"
    resp = app_client.put("/api/binary/location", json={"kernel_dir": str(target)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kernel_dir"] == str(target)
    assert data["is_default"] is False
    assert target.is_dir()  # created on demand
    assert db.get_setting(main.KERNEL_DIR_SETTING) == str(target)
    assert effective_kernel_dir() == target
    reset.assert_called_once()
    start.assert_called_once()

    # GET reflects the change
    resp = app_client.get("/api/binary/location")
    assert resp.json()["kernel_dir"] == str(target)


def test_put_location_native_rescans_without_download(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Native mode: changing the location re-scans for kernels, never downloads."""
    from backend.tests.test_kernel_manager import make_kernel

    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    start = MagicMock()
    monkeypatch.setattr(main.binary_mgr, "start", start)

    empty = tmp_path / "empty"
    resp = app_client.put("/api/binary/location", json={"kernel_dir": str(empty)})
    assert resp.status_code == 200
    start.assert_not_called()
    assert main.binary_mgr.ready is False

    stocked = tmp_path / "stocked"
    stocked.mkdir()
    make_kernel(stocked, "146.0.7680.177.5")
    resp = app_client.put("/api/binary/location", json={"kernel_dir": str(stocked)})
    assert resp.status_code == 200
    start.assert_not_called()
    assert main.binary_mgr.ready is True


def test_put_location_rejects_relative_path(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(KERNEL_DIR_ENV, raising=False)
    resp = app_client.put("/api/binary/location", json={"kernel_dir": "relative/dir"})
    assert resp.status_code == 400
    assert db.get_setting(main.KERNEL_DIR_SETTING) is None


def test_put_location_refused_while_downloading(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(main.binary_mgr, "downloading", True)
    resp = app_client.put("/api/binary/location", json={"kernel_dir": str(tmp_path)})
    assert resp.status_code == 409


def test_put_empty_resets_to_default(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv(KERNEL_DIR_ENV, str(tmp_path))
    db.set_setting(main.KERNEL_DIR_SETTING, str(tmp_path))
    monkeypatch.setattr(main.binary_mgr, "reset", MagicMock())
    monkeypatch.setattr(main.binary_mgr, "start", MagicMock())

    resp = app_client.put("/api/binary/location", json={"kernel_dir": None})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_default"] is True
    assert data["kernel_dir"] == str(default_kernel_dir())
    assert db.get_setting(main.KERNEL_DIR_SETTING) is None
    assert effective_kernel_dir() == default_kernel_dir()


# ── native startup: readiness scan instead of download ───────────────────────


def test_native_lifespan_marks_ready_without_download(
    tmp_db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from unittest.mock import AsyncMock

    from backend.tests.test_kernel_manager import make_kernel

    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    start = MagicMock()
    monkeypatch.setattr(main.binary_mgr, "start", start)
    monkeypatch.setenv(KERNEL_DIR_ENV, str(tmp_path))

    # No kernel installed → not ready, and no download was started
    with TestClient(main.app):
        assert main.binary_mgr.ready is False
        assert main.binary_mgr.downloading is False
    start.assert_not_called()

    # Kernel present → ready at startup, still no download
    make_kernel(tmp_path, "146.0.7680.177.5")
    with TestClient(main.app):
        assert main.binary_mgr.ready is True
    start.assert_not_called()


def test_vnc_lifespan_still_starts_download(
    tmp_db, monkeypatch: pytest.MonkeyPatch
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main, "use_vnc", lambda: True)
    start = MagicMock()
    monkeypatch.setattr(main.binary_mgr, "start", start)

    with TestClient(main.app):
        pass
    start.assert_called_once()
