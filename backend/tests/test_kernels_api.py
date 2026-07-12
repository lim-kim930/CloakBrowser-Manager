"""Tests for the kernel management REST endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import kernel_manager as km
from backend import main
from backend.config import KERNEL_DIR_ENV
from backend.tests.test_kernel_manager import make_kernel


@pytest.fixture()
def kernel_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "kernels"
    root.mkdir()
    monkeypatch.setenv(KERNEL_DIR_ENV, str(root))
    return root


def test_list_kernels_empty(app_client: TestClient, kernel_root: Path):
    resp = app_client.get("/api/kernels")
    assert resp.status_code == 200
    data = resp.json()
    assert data["kernels"] == []
    assert data["default_version"] is None
    assert data["kernel_dir"] == str(kernel_root)


def test_list_kernels_reports_installs(app_client: TestClient, kernel_root: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    make_kernel(kernel_root, "148.0.7778.215.2")
    data = app_client.get("/api/kernels").json()
    assert [k["version"] for k in data["kernels"]] == [
        "148.0.7778.215.2",
        "146.0.7680.177.5",
    ]
    assert all(k["in_use"] is False for k in data["kernels"])


def test_import_kernel_folder(app_client: TestClient, kernel_root: Path, tmp_path: Path):
    src = tmp_path / "chromium-1.2.3.4"
    exe = src / km._exe_relpath()
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fake")

    resp = app_client.post("/api/kernels/import", json={"source_path": str(src)})
    assert resp.status_code == 200
    assert [k["version"] for k in resp.json()["kernels"]] == ["1.2.3.4"]
    assert km.kernel_installed("1.2.3.4")


def test_import_kernel_conflict(app_client: TestClient, kernel_root: Path, tmp_path: Path):
    make_kernel(kernel_root, "1.2.3.4")
    src = tmp_path / "chromium-1.2.3.4"
    exe = src / km._exe_relpath()
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fake")

    resp = app_client.post("/api/kernels/import", json={"source_path": str(src)})
    assert resp.status_code == 409


def test_import_kernel_bad_source(app_client: TestClient, kernel_root: Path, tmp_path: Path):
    resp = app_client.post(
        "/api/kernels/import",
        json={"source_path": str(tmp_path / "missing"), "version": "1.2.3.4"},
    )
    assert resp.status_code == 400


def test_import_kernel_version_required(
    app_client: TestClient, kernel_root: Path, tmp_path: Path
):
    src = tmp_path / "mystery"
    exe = src / km._exe_relpath()
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fake")

    resp = app_client.post("/api/kernels/import", json={"source_path": str(src)})
    assert resp.status_code == 422


def test_import_marks_native_ready(
    app_client: TestClient, kernel_root: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    main.binary_mgr.ready = False
    src = tmp_path / "chromium-1.2.3.4"
    exe = src / km._exe_relpath()
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fake")

    resp = app_client.post("/api/kernels/import", json={"source_path": str(src)})
    assert resp.status_code == 200
    assert main.binary_mgr.ready is True


def test_delete_kernel(app_client: TestClient, kernel_root: Path):
    make_kernel(kernel_root, "1.2.3.4")
    resp = app_client.delete("/api/kernels/1.2.3.4")
    assert resp.status_code == 200
    assert resp.json()["kernels"] == []
    assert not km.kernel_installed("1.2.3.4")


def test_delete_kernel_not_found(app_client: TestClient, kernel_root: Path):
    resp = app_client.delete("/api/kernels/9.9.9.9")
    assert resp.status_code == 404


def test_delete_kernel_malformed_version(app_client: TestClient, kernel_root: Path):
    resp = app_client.delete("/api/kernels/not-a-version")
    assert resp.status_code == 422


def test_delete_kernel_in_use(app_client: TestClient, kernel_root: Path):
    from types import SimpleNamespace

    make_kernel(kernel_root, "1.2.3.4")
    # Stand-in for a RunningProfile — the endpoint only reads kernel_version
    main.browser_mgr.running["p1"] = SimpleNamespace(kernel_version="1.2.3.4")
    try:
        resp = app_client.delete("/api/kernels/1.2.3.4")
        assert resp.status_code == 409
        assert km.kernel_installed("1.2.3.4")
    finally:
        main.browser_mgr.running.pop("p1", None)


def test_delete_updates_native_readiness(
    app_client: TestClient, kernel_root: Path, monkeypatch
):
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    make_kernel(kernel_root, "1.2.3.4")
    main.binary_mgr.ready = True

    resp = app_client.delete("/api/kernels/1.2.3.4")
    assert resp.status_code == 200
    assert main.binary_mgr.ready is False


def test_set_default_kernel(app_client: TestClient, kernel_root: Path):
    make_kernel(kernel_root, "1.2.3.4")
    resp = app_client.put("/api/kernels/default", json={"version": "1.2.3.4"})
    assert resp.status_code == 200
    assert resp.json()["default_version"] == "1.2.3.4"

    # Clearing falls back to "newest wins"
    resp = app_client.put("/api/kernels/default", json={"version": None})
    assert resp.status_code == 200
    assert resp.json()["default_version"] is None


def test_set_default_kernel_not_installed(app_client: TestClient, kernel_root: Path):
    resp = app_client.put("/api/kernels/default", json={"version": "9.9.9.9"})
    assert resp.status_code == 400


def test_delete_default_kernel_clears_setting(app_client: TestClient, kernel_root: Path):
    make_kernel(kernel_root, "1.2.3.4")
    app_client.put("/api/kernels/default", json={"version": "1.2.3.4"})
    app_client.delete("/api/kernels/1.2.3.4")
    assert db.get_setting(km.DEFAULT_KERNEL_SETTING) is None
