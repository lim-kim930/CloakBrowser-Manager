"""Tests for the CloakBrowser kernel readiness tracker."""

from __future__ import annotations

from backend.binary_status import BinaryStatusTracker, run_ensure_binary


def test_initial_state_downloading():
    t = BinaryStatusTracker()
    assert t.snapshot() == {"state": "downloading", "version": None, "error": None}


def test_mark_ready():
    t = BinaryStatusTracker()
    t.mark_ready("0.4.10")
    snap = t.snapshot()
    assert snap["state"] == "ready"
    assert snap["version"] == "0.4.10"
    assert snap["error"] is None


def test_mark_error():
    t = BinaryStatusTracker()
    t.mark_error("download failed")
    snap = t.snapshot()
    assert snap["state"] == "error"
    assert snap["error"] == "download failed"


def test_run_ensure_binary_success():
    t = BinaryStatusTracker()
    calls = []
    run_ensure_binary(t, ensure_fn=lambda: calls.append("ensure"), version_fn=lambda: "1.2.3")
    assert calls == ["ensure"]
    assert t.snapshot() == {"state": "ready", "version": "1.2.3", "error": None}


def test_run_ensure_binary_download_fails():
    t = BinaryStatusTracker()

    def boom():
        raise RuntimeError("no network")

    run_ensure_binary(t, ensure_fn=boom, version_fn=lambda: "1.2.3")
    snap = t.snapshot()
    assert snap["state"] == "error"
    assert "no network" in snap["error"]


def test_run_ensure_binary_version_failure_still_ready():
    t = BinaryStatusTracker()

    def bad_version():
        raise RuntimeError("cannot read version")

    run_ensure_binary(t, ensure_fn=lambda: None, version_fn=bad_version)
    assert t.snapshot()["state"] == "ready"
    assert t.snapshot()["version"] is None
