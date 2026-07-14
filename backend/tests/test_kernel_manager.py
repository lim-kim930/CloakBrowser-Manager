"""Tests for kernel import / link / validation logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend import database as db, kernel_manager as km


@pytest.fixture()
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(cache))
    return cache


def make_kernel_dir(base: Path, name: str) -> Path:
    """Create a fake extracted kernel directory containing the platform exe."""
    d = base / name
    exe = d / km.exe_relpath()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake")
    return d


class TestDetectVersion:
    def test_from_directory_name(self, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-146.0.7680.177.5")
        assert km.detect_version(d) == "146.0.7680.177.5"

    def test_from_directory_name_pro_suffix(self, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-146.0.7680.177.5-pro")
        assert km.detect_version(d) == "146.0.7680.177.5"

    def test_from_exe_version_output(self, tmp_path, monkeypatch):
        d = make_kernel_dir(tmp_path, "my-kernel")
        monkeypatch.setattr(km, "_run_version_probe", lambda exe: "Chromium 146.0.7680.177")
        assert km.detect_version(d) == "146.0.7680.177"

    def test_undetectable_raises(self, tmp_path, monkeypatch):
        d = make_kernel_dir(tmp_path, "my-kernel")
        monkeypatch.setattr(km, "_run_version_probe", lambda exe: "")
        with pytest.raises(km.KernelImportError, match="version"):
            km.detect_version(d)


class TestImportKernel:
    def test_import_creates_link_and_row(self, cache, tmp_db, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        kernel = km.import_kernel(str(d))
        assert kernel["version"] == "1.2.3.4"
        assert kernel["source"] == "imported"
        assert kernel["source_path"] == str(d)
        assert kernel["is_default"] is True  # first kernel
        assert km.kernel_exe("1.2.3.4").exists()  # resolves through the link

    def test_import_missing_exe_rejected(self, cache, tmp_db, tmp_path):
        d = tmp_path / "chromium-1.2.3.4"
        d.mkdir()
        with pytest.raises(km.KernelImportError, match="executable"):
            km.import_kernel(str(d))

    def test_import_nonexistent_dir_rejected(self, cache, tmp_db, tmp_path):
        with pytest.raises(km.KernelImportError, match="directory"):
            km.import_kernel(str(tmp_path / "missing"))

    def test_import_duplicate_version_rejected(self, cache, tmp_db, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        km.import_kernel(str(d))
        d2 = make_kernel_dir(tmp_path / "other", "chromium-1.2.3.4")
        with pytest.raises(km.KernelImportError, match="already"):
            km.import_kernel(str(d2))

    def test_import_replaces_stale_link(self, cache, tmp_db, tmp_path):
        """A leftover link without a DB row (crash残留) must not block import."""
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        km.create_link("1.2.3.4", d)  # link exists, no DB row
        kernel = km.import_kernel(str(d))
        assert kernel["version"] == "1.2.3.4"

    def test_import_replaces_dangling_link(self, cache, tmp_db, tmp_path):
        """A link whose target was deleted evades exists() — must still be replaced."""
        import shutil

        old = make_kernel_dir(tmp_path / "old", "chromium-1.2.3.4")
        km.create_link("1.2.3.4", old)
        shutil.rmtree(old)  # link now dangles
        new = make_kernel_dir(tmp_path / "new", "chromium-1.2.3.4")
        kernel = km.import_kernel(str(new))
        assert kernel["version"] == "1.2.3.4"
        assert km.kernel_exe("1.2.3.4").exists()

    def test_import_cache_copy_adopts_in_place(self, cache, tmp_db):
        """Importing the cache slot itself (pre-library download) registers it
        as downloaded instead of trying to replace the directory with a link."""
        exe = km.kernel_exe("2.0.0.0")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        kernel = km.import_kernel(str(km.kernel_dir("2.0.0.0")))
        assert kernel["source"] == "downloaded"
        assert kernel["source_path"] is None
        assert km.kernel_is_valid("2.0.0.0")
        assert not km._is_link(km.kernel_dir("2.0.0.0"))  # still a real dir

    def test_import_other_copy_of_cached_version_rejected(self, cache, tmp_db, tmp_path):
        """Cache slot holds a real dir of the same version → clear error, no rmdir."""
        exe = km.kernel_exe("2.0.0.0")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        d = make_kernel_dir(tmp_path, "chromium-2.0.0.0")
        with pytest.raises(km.KernelImportError, match="cache"):
            km.import_kernel(str(d))
        assert km.kernel_exe("2.0.0.0").exists()  # cached copy untouched


class TestRemoveKernelFiles:
    def test_remove_imported_keeps_source(self, cache, tmp_db, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        kernel = km.import_kernel(str(d))
        km.remove_kernel_files(kernel)
        assert not (cache / "chromium-1.2.3.4").exists()  # link gone
        assert (d / km.exe_relpath()).exists()  # user's files untouched

    def test_remove_downloaded_deletes_dir(self, cache, tmp_db):
        exe = km.kernel_exe("2.0.0.0")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        kernel = db.create_kernel("2.0.0.0", "downloaded")
        km.remove_kernel_files(kernel)
        assert not (cache / "chromium-2.0.0.0").exists()

    def test_remove_imported_dangling_link(self, cache, tmp_db, tmp_path):
        """A dangling link (user deleted the source dir) must still be removed."""
        import os
        import shutil

        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        kernel = km.import_kernel(str(d))
        shutil.rmtree(d)  # link now dangles
        km.remove_kernel_files(kernel)
        assert not os.path.lexists(km.kernel_dir("1.2.3.4"))


class TestValidity:
    def test_valid_and_invalid(self, cache, tmp_db, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        km.import_kernel(str(d))
        assert km.kernel_is_valid("1.2.3.4") is True
        # User deletes their original directory → link dangles
        import shutil
        shutil.rmtree(d)
        assert km.kernel_is_valid("1.2.3.4") is False
