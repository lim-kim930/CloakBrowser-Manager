"""Tests for backend.kernel_manager — scan/resolve/import/delete."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backend import database as db
from backend import kernel_manager as km
from backend.config import KERNEL_DIR_ENV


@pytest.fixture()
def kernel_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the kernel storage dir at an empty temp directory."""
    root = tmp_path / "kernels"
    root.mkdir()
    monkeypatch.setenv(KERNEL_DIR_ENV, str(root))
    return root


def make_kernel(root: Path, version: str) -> Path:
    """Create a fake installed kernel dir with the platform executable."""
    kdir = root / f"chromium-{version}"
    exe = kdir / km._exe_relpath()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake-chrome")
    return kdir


# ── layout guard (must match the cloakbrowser package's naming) ──────────────


def test_kernel_dir_layout_matches_package(kernel_root: Path):
    kdir = km._kernel_dir("146.0.7680.177.5")
    assert kdir == kernel_root / "chromium-146.0.7680.177.5"
    exe = km._kernel_exe("146.0.7680.177.5")
    assert exe == kdir / km._exe_relpath()
    assert exe.name in ("chrome.exe", "chrome", "Chromium")


# ── list / installed ─────────────────────────────────────────────────────────


def test_list_kernels_empty_when_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(KERNEL_DIR_ENV, str(tmp_path / "nope"))
    assert km.list_kernels() == []
    assert km.any_kernel_installed() is False


def test_list_kernels_scans_and_sorts(kernel_root: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    make_kernel(kernel_root, "148.0.7778.215.2")
    make_kernel(kernel_root, "145.0.7632.109")
    # skipped: pro dir, invalid name, dir without executable
    make_kernel(kernel_root, "147.0.0.0-pro")  # invalid version suffix
    (kernel_root / "chromium-junk").mkdir()
    (kernel_root / "chromium-149.0.0.0").mkdir()  # no exe inside
    (kernel_root / "unrelated").mkdir()

    kernels = km.list_kernels()
    assert [k["version"] for k in kernels] == [
        "148.0.7778.215.2",
        "146.0.7680.177.5",
        "145.0.7632.109",
    ]
    assert all(k["size"] and k["size"] > 0 for k in kernels)
    assert all(k["pro"] is False for k in kernels)
    assert km.any_kernel_installed() is True


def test_kernel_installed(kernel_root: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    assert km.kernel_installed("146.0.7680.177.5") is True
    assert km.kernel_installed("146.0.7680.177.9") is False
    assert km.kernel_installed("not-a-version") is False
    assert km.kernel_installed("") is False


# ── default version ──────────────────────────────────────────────────────────


def test_set_and_get_default_version(kernel_root: Path, tmp_db: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    km.set_default_version("146.0.7680.177.5")
    assert km.get_default_version() == "146.0.7680.177.5"
    km.set_default_version(None)
    assert km.get_default_version() is None


def test_set_default_requires_installed(kernel_root: Path, tmp_db: Path):
    with pytest.raises(km.KernelNotFoundError):
        km.set_default_version("1.2.3.4")
    with pytest.raises(km.KernelVersionError):
        km.set_default_version("bogus")


def test_get_default_ignores_stale_setting(kernel_root: Path, tmp_db: Path):
    kdir = make_kernel(kernel_root, "146.0.7680.177.5")
    km.set_default_version("146.0.7680.177.5")
    import shutil

    shutil.rmtree(kdir)  # kernel removed outside the app
    assert km.get_default_version() is None


# ── resolve_kernel_version ───────────────────────────────────────────────────


def test_resolve_explicit_installed(kernel_root: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    assert km.resolve_kernel_version("146.0.7680.177.5") == "146.0.7680.177.5"


def test_resolve_explicit_missing_raises(kernel_root: Path):
    with pytest.raises(ValueError, match="not installed"):
        km.resolve_kernel_version("146.0.7680.177.5")


def test_resolve_explicit_malformed_raises(kernel_root: Path):
    with pytest.raises(ValueError, match="Invalid kernel version"):
        km.resolve_kernel_version("../../etc")


def test_resolve_falls_back_to_default_then_newest(kernel_root: Path, tmp_db: Path):
    make_kernel(kernel_root, "146.0.7680.177.5")
    make_kernel(kernel_root, "148.0.7778.215.2")
    # No default → newest
    assert km.resolve_kernel_version(None) == "148.0.7778.215.2"
    # Default wins over newest
    km.set_default_version("146.0.7680.177.5")
    assert km.resolve_kernel_version(None) == "146.0.7680.177.5"
    # Empty string behaves like None
    assert km.resolve_kernel_version("  ") == "146.0.7680.177.5"


def test_resolve_none_when_nothing_installed(kernel_root: Path, tmp_db: Path):
    assert km.resolve_kernel_version(None) is None


# ── import: folder sources ───────────────────────────────────────────────────


def test_import_folder_named_chromium_copies_from_outside(
    kernel_root: Path, tmp_path: Path
):
    src = tmp_path / "downloads" / "chromium-146.0.7680.177.5"
    (src / km._exe_relpath()).parent.mkdir(parents=True)
    (src / km._exe_relpath()).write_bytes(b"fake")

    info = km.import_kernel(str(src))
    assert info["version"] == "146.0.7680.177.5"
    assert km.kernel_installed("146.0.7680.177.5")
    assert src.exists()  # copied, original kept


def test_import_folder_inside_kernel_dir_renames(kernel_root: Path):
    src = kernel_root / "extracted-stuff"
    (src / km._exe_relpath()).parent.mkdir(parents=True)
    (src / km._exe_relpath()).write_bytes(b"fake")

    km.import_kernel(str(src), version="1.2.3.4")
    assert km.kernel_installed("1.2.3.4")
    assert not src.exists()  # moved, not copied


def test_import_folder_already_in_place_is_noop(kernel_root: Path):
    kdir = make_kernel(kernel_root, "1.2.3.4")
    info = km.import_kernel(str(kdir))
    assert info["version"] == "1.2.3.4"
    assert km.kernel_installed("1.2.3.4")


def test_import_folder_locates_single_kernel_subdir(kernel_root: Path, tmp_path: Path):
    parent = tmp_path / "unpacked"
    inner = parent / "chromium-1.2.3.4"
    (inner / km._exe_relpath()).parent.mkdir(parents=True)
    (inner / km._exe_relpath()).write_bytes(b"fake")

    info = km.import_kernel(str(parent))
    assert info["version"] == "1.2.3.4"
    assert km.kernel_installed("1.2.3.4")


def test_import_folder_without_version_raises(kernel_root: Path, tmp_path: Path):
    src = tmp_path / "mystery"
    (src / km._exe_relpath()).parent.mkdir(parents=True)
    (src / km._exe_relpath()).write_bytes(b"fake")
    with pytest.raises(km.KernelVersionError):
        km.import_kernel(str(src))


def test_import_existing_version_conflicts(kernel_root: Path, tmp_path: Path):
    make_kernel(kernel_root, "1.2.3.4")
    src = tmp_path / "chromium-1.2.3.4"
    (src / km._exe_relpath()).parent.mkdir(parents=True)
    (src / km._exe_relpath()).write_bytes(b"fake")
    with pytest.raises(km.KernelExistsError):
        km.import_kernel(str(src))


def test_import_folder_without_kernel_raises(kernel_root: Path, tmp_path: Path):
    src = tmp_path / "empty"
    src.mkdir()
    with pytest.raises(km.KernelSourceError):
        km.import_kernel(str(src), version="1.2.3.4")


def test_import_missing_source_raises(kernel_root: Path, tmp_path: Path):
    with pytest.raises(km.KernelSourceError):
        km.import_kernel(str(tmp_path / "nope.zip"), version="1.2.3.4")


# ── import: zip sources ──────────────────────────────────────────────────────


def _exe_zip_name() -> str:
    return km._exe_relpath().as_posix()


def test_import_zip_with_wrapping_dir(kernel_root: Path, tmp_path: Path):
    archive = tmp_path / "cloakbrowser-windows-x64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"cloakbrowser-win/{_exe_zip_name()}", b"fake")
        zf.writestr("cloakbrowser-win/resources.pak", b"data")

    info = km.import_kernel(str(archive), version="146.0.7680.177.5")
    assert info["version"] == "146.0.7680.177.5"
    assert km.kernel_installed("146.0.7680.177.5")
    # wrapping dir was flattened
    assert (km._kernel_dir("146.0.7680.177.5") / "resources.pak").is_file()
    # no staging leftovers
    assert not list(kernel_root.glob(".kernel-import-*"))


def test_import_zip_flat_layout(kernel_root: Path, tmp_path: Path):
    archive = tmp_path / "kernel.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_exe_zip_name(), b"fake")

    km.import_kernel(str(archive), version="1.2.3.4")
    assert km.kernel_installed("1.2.3.4")


def test_import_zip_requires_version(kernel_root: Path, tmp_path: Path):
    archive = tmp_path / "kernel.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_exe_zip_name(), b"fake")
    with pytest.raises(km.KernelVersionError):
        km.import_kernel(str(archive))


def test_import_zip_rejects_path_traversal(kernel_root: Path, tmp_path: Path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", b"boom")
    with pytest.raises(km.KernelSourceError, match="unsafe path"):
        km.import_kernel(str(archive), version="1.2.3.4")
    assert not km.kernel_installed("1.2.3.4")
    assert not list(kernel_root.glob(".kernel-import-*"))
    assert not (kernel_root / "evil.txt").exists()


def test_import_zip_without_kernel_raises(kernel_root: Path, tmp_path: Path):
    archive = tmp_path / "no-kernel.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", b"hello")
    with pytest.raises(km.KernelSourceError):
        km.import_kernel(str(archive), version="1.2.3.4")
    assert not list(kernel_root.glob(".kernel-import-*"))


def test_import_non_zip_file_raises(kernel_root: Path, tmp_path: Path):
    src = tmp_path / "kernel.tar.gz"
    src.write_bytes(b"not a zip")
    with pytest.raises(km.KernelSourceError):
        km.import_kernel(str(src), version="1.2.3.4")


# ── delete ───────────────────────────────────────────────────────────────────


def test_delete_kernel(kernel_root: Path, tmp_db: Path):
    make_kernel(kernel_root, "1.2.3.4")
    km.delete_kernel("1.2.3.4")
    assert not km.kernel_installed("1.2.3.4")


def test_delete_clears_default(kernel_root: Path, tmp_db: Path):
    make_kernel(kernel_root, "1.2.3.4")
    km.set_default_version("1.2.3.4")
    km.delete_kernel("1.2.3.4")
    assert db.get_setting(km.DEFAULT_KERNEL_SETTING) is None


def test_delete_rejects_malformed_version(kernel_root: Path):
    with pytest.raises(km.KernelVersionError):
        km.delete_kernel("../../home")


def test_delete_missing_kernel_raises(kernel_root: Path):
    with pytest.raises(km.KernelNotFoundError):
        km.delete_kernel("9.9.9.9")
