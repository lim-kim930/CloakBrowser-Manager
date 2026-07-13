"""Tests for the /api/kernels endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import database as db, kernel_manager as km


def make_kernel_dir(base: Path, name: str) -> Path:
    d = base / name
    exe = d / km.exe_relpath()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake")
    return d


class TestKernelsApi:
    def test_list_includes_validity_and_default(self, app_client):
        body = app_client.get("/api/kernels").json()
        assert len(body) == 1
        k = body[0]
        assert k["version"] == "1.0.0.0"
        assert k["is_default"] is True
        assert k["valid"] is True
        assert k["profile_count"] == 0

    def test_import_ok(self, app_client, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-3.0.0.0")
        resp = app_client.post("/api/kernels/import", json={"path": str(d)})
        assert resp.status_code == 201
        assert resp.json()["version"] == "3.0.0.0"
        assert resp.json()["source"] == "imported"

    def test_import_bad_dir_400(self, app_client, tmp_path):
        resp = app_client.post("/api/kernels/import", json={"path": str(tmp_path / "nope")})
        assert resp.status_code == 400
        assert "directory" in resp.json()["detail"]

    def test_set_default(self, app_client, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-3.0.0.0")
        k = app_client.post("/api/kernels/import", json={"path": str(d)}).json()
        assert app_client.put(f"/api/kernels/{k['id']}/default").json() == {"ok": True}
        listed = {x["version"]: x for x in app_client.get("/api/kernels").json()}
        assert listed["3.0.0.0"]["is_default"] is True
        assert listed["1.0.0.0"]["is_default"] is False

    def test_set_default_404(self, app_client):
        assert app_client.put("/api/kernels/nope/default").status_code == 404

    def test_delete_imported_keeps_source_dir(self, app_client, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-3.0.0.0")
        k = app_client.post("/api/kernels/import", json={"path": str(d)}).json()
        assert app_client.delete(f"/api/kernels/{k['id']}").json() == {"ok": True}
        assert (d / km.exe_relpath()).exists()
        assert not km.kernel_dir("3.0.0.0").exists()

    def test_delete_404(self, app_client):
        assert app_client.delete("/api/kernels/nope").status_code == 404

    def test_delete_in_use_by_running_profile_409(self, app_client, monkeypatch):
        from backend import main

        kernel = db.list_kernels()[0]
        p = app_client.post("/api/profiles", json={"name": "P"}).json()
        # Simulate the profile running (it resolves to the default kernel)
        monkeypatch.setitem(main.browser_mgr.running, p["id"], object())
        resp = app_client.delete(f"/api/kernels/{kernel['id']}")
        assert resp.status_code == 409

    def test_download_status_idle(self, app_client):
        body = app_client.get("/api/kernels/download/status").json()
        assert body["state"] == "idle"

    def test_download_starts_thread(self, app_client, monkeypatch):
        from backend import binary_status

        started = []
        monkeypatch.setattr(binary_status.download, "start", lambda: started.append(1) or True)
        assert app_client.post("/api/kernels/download").json() == {"ok": True}
        assert started

    def test_download_conflict_409(self, app_client, monkeypatch):
        from backend import binary_status

        monkeypatch.setattr(binary_status.download, "start", lambda: False)
        assert app_client.post("/api/kernels/download").status_code == 409
