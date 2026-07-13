"""Tests for kernel library status and the on-demand download runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import binary_status, database as db


class TestLibrarySnapshot:
    def test_empty_library_is_none(self, tmp_db):
        assert binary_status.library_snapshot() == {
            "state": "none", "version": None, "error": None,
        }

    def test_with_kernel_is_ready(self, tmp_db):
        db.create_kernel("1.0.0.0", "downloaded")
        snap = binary_status.library_snapshot()
        assert snap["state"] == "ready"
        assert snap["version"] == "1.0.0.0"

    def test_download_in_progress_wins(self, tmp_db):
        db.create_kernel("1.0.0.0", "downloaded")
        binary_status.download._set("downloading", None)
        try:
            assert binary_status.library_snapshot()["state"] == "downloading"
        finally:
            binary_status.download._set("idle", None)

    def test_failed_download_empty_library_is_error(self, tmp_db):
        binary_status.download._set("error", "boom")
        try:
            snap = binary_status.library_snapshot()
            assert snap["state"] == "error"
            assert snap["error"] == "boom"
        finally:
            binary_status.download._set("idle", None)

    def test_failed_download_with_kernel_still_ready(self, tmp_db):
        db.create_kernel("1.0.0.0", "downloaded")
        binary_status.download._set("error", "boom")
        try:
            assert binary_status.library_snapshot()["state"] == "ready"
        finally:
            binary_status.download._set("idle", None)


class TestDownloadRunner:
    def test_run_download_registers_kernel(self, tmp_db, tmp_path, monkeypatch):
        exe = tmp_path / "chromium-9.9.9.9" / "chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        binary_status.run_download(binary_status.download, lambda: str(exe))
        assert binary_status.download.snapshot()["state"] == "ready"
        kernels = db.list_kernels()
        assert len(kernels) == 1
        assert kernels[0]["version"] == "9.9.9.9"
        assert kernels[0]["source"] == "downloaded"
        binary_status.download._set("idle", None)

    def test_run_download_existing_version_no_duplicate(self, tmp_db, tmp_path):
        db.create_kernel("9.9.9.9", "downloaded")
        exe = tmp_path / "chromium-9.9.9.9" / "chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        binary_status.run_download(binary_status.download, lambda: str(exe))
        assert len(db.list_kernels()) == 1
        binary_status.download._set("idle", None)

    def test_run_download_failure_sets_error(self, tmp_db):
        def boom():
            raise RuntimeError("network down")

        binary_status.run_download(binary_status.download, boom)
        snap = binary_status.download.snapshot()
        assert snap["state"] == "error"
        assert "network down" in snap["error"]
        binary_status.download._set("idle", None)

    def test_start_rejects_concurrent(self, tmp_db, monkeypatch):
        binary_status.download._set("downloading", None)
        try:
            assert binary_status.download.start() is False
        finally:
            binary_status.download._set("idle", None)
