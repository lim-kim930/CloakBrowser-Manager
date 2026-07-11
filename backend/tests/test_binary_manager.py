"""Tests for BinaryManager background download state machine."""
from __future__ import annotations

import sys

import pytest

from backend.binary_manager import BinaryManager


@pytest.mark.asyncio
async def test_start_then_wait_ready_success(monkeypatch):
    calls = {"n": 0}

    def fake_ensure():
        calls["n"] += 1
        return "/fake/chrome"

    monkeypatch.setattr(sys.modules["cloakbrowser.download"], "ensure_binary", fake_ensure)

    m = BinaryManager()
    assert m.status() == {"ready": False, "downloading": False, "error": None}
    m.start()
    assert m.downloading is True
    ok = await m.wait_ready()
    assert ok is True
    assert m.ready is True
    assert m.downloading is False
    assert m.error is None
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_download_failure_records_error(monkeypatch):
    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(sys.modules["cloakbrowser.download"], "ensure_binary", boom)

    m = BinaryManager()
    m.start()
    ok = await m.wait_ready()
    assert ok is False
    assert m.ready is False
    assert m.downloading is False
    assert "network down" in m.error


@pytest.mark.asyncio
async def test_start_is_idempotent_when_downloading(monkeypatch):
    monkeypatch.setattr(
        sys.modules["cloakbrowser.download"], "ensure_binary", lambda: "/fake/chrome"
    )
    m = BinaryManager()
    m.start()
    first_task = m._task
    m.start()  # should not replace the in-flight task
    assert m._task is first_task
    await m.wait_ready()
