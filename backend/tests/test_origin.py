"""Tests for OriginCheckMiddleware and CORS configuration."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from backend import main


def test_write_with_unlisted_origin_403(app_client: TestClient):
    resp = app_client.post(
        "/api/profiles", json={"name": "Evil"}, headers={"Origin": "http://evil.com"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Origin not allowed"


def test_write_with_tauri_origin_allowed(app_client: TestClient):
    resp = app_client.post(
        "/api/profiles", json={"name": "Tauri"}, headers={"Origin": "http://tauri.localhost"}
    )
    assert resp.status_code == 201


def test_write_with_dev_origin_allowed(app_client: TestClient):
    resp = app_client.post(
        "/api/profiles", json={"name": "Dev"}, headers={"Origin": "http://localhost:5173"}
    )
    assert resp.status_code == 201


def test_write_without_origin_allowed(app_client: TestClient):
    """curl / Playwright / the Rust shell send no Origin — must pass."""
    resp = app_client.post("/api/profiles", json={"name": "NoOrigin"})
    assert resp.status_code == 201


def test_get_with_unlisted_origin_not_blocked(app_client: TestClient):
    """Reads are not blocked (CORS stops browsers from reading the response)."""
    resp = app_client.get("/api/profiles", headers={"Origin": "http://evil.com"})
    assert resp.status_code == 200


def test_delete_with_unlisted_origin_403(app_client: TestClient):
    resp = app_client.delete(
        "/api/profiles/some-id", headers={"Origin": "http://evil.com"}
    )
    assert resp.status_code == 403


def test_cors_headers_on_allowed_origin(app_client: TestClient):
    resp = app_client.get("/api/profiles", headers={"Origin": "http://tauri.localhost"})
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_extended_allow_origin_respected(app_client: TestClient):
    """--allow-origin extends the shared list in place at runtime."""
    main.ALLOWED_ORIGINS.append("http://extra.example")
    try:
        resp = app_client.post(
            "/api/profiles", json={"name": "Extra"}, headers={"Origin": "http://extra.example"}
        )
        assert resp.status_code == 201
    finally:
        main.ALLOWED_ORIGINS.remove("http://extra.example")


def test_ws_upgrade_unlisted_origin_rejected(app_client: TestClient):
    with pytest.raises(Exception):
        with app_client.websocket_connect(
            "/api/profiles/any/cdp", headers={"Origin": "http://evil.com"}
        ):
            pass


def test_ws_upgrade_no_origin_reaches_endpoint(app_client: TestClient):
    """No Origin passes the middleware; endpoint then closes 4004 (not running)."""
    try:
        with app_client.websocket_connect("/api/profiles/any/cdp"):
            pass
    except Exception as exc:
        assert "4403" not in str(exc)


def test_unhandled_error_500_carries_cors_headers(tmp_db, installed_kernel, monkeypatch):
    """Unhandled exceptions are answered outside CORSMiddleware; without the
    custom handler adding the header, the WebView blocks the response and the
    UI shows an opaque "Failed to fetch" instead of the error message."""
    from unittest.mock import AsyncMock

    from backend import kernel_manager

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(kernel_manager, "import_kernel", boom)
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/kernels/import",
            json={"path": "X:\\nope"},
            headers={"Origin": "http://tauri.localhost"},
        )
    assert resp.status_code == 500
    assert "boom" in resp.json()["detail"]
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"
