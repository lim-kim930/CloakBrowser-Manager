"""Kernel library filesystem layer.

Imported kernels stay at the user's original path; a link named
chromium-{version} inside the cloakbrowser cache dir makes them resolvable
by ensure_binary(browser_version=...) without copying or network access.
Windows uses an NTFS junction (no admin rights needed), POSIX a symlink.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import database as db


class KernelImportError(ValueError):
    """User-facing import failure (bad directory, undetectable version, duplicate)."""


_VERSION_RE = re.compile(r"\d+(?:\.\d+){2,4}")


def cache_dir() -> Path:
    env = os.environ.get("CLOAKBROWSER_CACHE_DIR")
    return Path(env) if env else Path.home() / ".cloakbrowser"


def exe_relpath() -> Path:
    if sys.platform == "win32":
        return Path("chrome.exe")
    if sys.platform == "darwin":
        return Path("Chromium.app/Contents/MacOS/Chromium")
    return Path("chrome")


def kernel_dir(version: str) -> Path:
    return cache_dir() / f"chromium-{version}"


def kernel_exe(version: str) -> Path:
    return kernel_dir(version) / exe_relpath()


def kernel_is_valid(version: str) -> bool:
    return kernel_exe(version).exists()


def _run_version_probe(exe: Path) -> str:
    """Run `exe --version` and return stdout. Separate function so tests can stub it."""
    try:
        result = subprocess.run(
            [str(exe), "--version"], capture_output=True, text=True, timeout=15
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_version(directory: Path) -> str:
    m = re.fullmatch(r"chromium-(\d+(?:\.\d+){2,4})(?:-pro)?", directory.name)
    if m:
        return m.group(1)
    output = _run_version_probe(directory / exe_relpath())
    m2 = _VERSION_RE.search(output)
    if m2:
        return m2.group(0)
    raise KernelImportError(
        "Could not detect the kernel version. Check that the directory is an "
        "extracted CloakBrowser Chromium kernel."
    )


def _is_link(path: Path) -> bool:
    """True for a symlink or an NTFS junction (dangling ones included)."""
    return path.is_symlink() or path.is_junction()


def create_link(version: str, target: Path) -> None:
    """Create <cache>/chromium-{version} pointing at target. Replaces a stale link."""
    link = kernel_dir(version)
    link.parent.mkdir(parents=True, exist_ok=True)
    # lexists, not exists: a dangling link (deleted target) must be replaced too
    if os.path.lexists(link):
        _remove_link(link)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_link(link: Path) -> None:
    """Remove a junction/symlink WITHOUT touching its target."""
    if link.is_symlink():
        link.unlink()
    else:
        # NTFS junction: rmdir removes the reparse point only
        os.rmdir(link)


def import_kernel(directory: str) -> dict:
    target = Path(directory)
    if not target.is_dir():
        raise KernelImportError(f"Not a directory: {directory}")
    if not (target / exe_relpath()).exists():
        raise KernelImportError(
            f"Browser executable not found in the selected directory "
            f"(expected {exe_relpath()})"
        )
    version = detect_version(target)
    if db.get_kernel_by_version(version):
        raise KernelImportError(f"Kernel {version} is already in the library")
    link = kernel_dir(version)
    if os.path.lexists(link) and not _is_link(link):
        # A real directory occupies the cache slot: a download from before
        # the kernel library existed (files on disk, no DB row). Never
        # delete it to make room for a link.
        if os.path.normcase(os.path.realpath(target)) == os.path.normcase(
            os.path.realpath(link)
        ):
            # The user picked the cache copy itself — adopt it in place.
            # The files live in the cache, so it is a "downloaded" kernel:
            # deleting it later removes the directory, not a link.
            return db.create_kernel(version, "downloaded")
        raise KernelImportError(
            f"Kernel {version} already exists in the app's kernel cache "
            f"({link}). Import that directory instead to use it, or remove "
            f"it first."
        )
    create_link(version, target)
    return db.create_kernel(version, "imported", source_path=str(target))


def remove_kernel_files(kernel: dict) -> None:
    d = kernel_dir(kernel["version"])
    # lexists: a dangling link (deleted target) must still be cleaned up
    if not os.path.lexists(d):
        return
    if kernel["source"] == "imported":
        _remove_link(d)
    else:
        shutil.rmtree(d, ignore_errors=True)
