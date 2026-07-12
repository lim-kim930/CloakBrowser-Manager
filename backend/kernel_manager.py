"""Manage user-installed CloakBrowser kernels (browser binaries).

Kernels live side by side inside ``effective_kernel_dir()`` using the
cloakbrowser package's own layout: ``chromium-<version>/`` containing the
platform executable. Launching a profile pins that version via the package's
``browser_version`` argument, which resolves to this exact directory — so as
long as the directory exists, launches never touch the network.

This module deliberately imports nothing from the ``cloakbrowser`` package:
the on-disk naming is a stable documented contract (mirrored from
``cloakbrowser.config.get_binary_dir/get_binary_path``), and the backend test
suite replaces the whole package with mocks.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import database as db
from .config import effective_kernel_dir

logger = logging.getLogger("cloakbrowser.manager.kernel")

# settings-table key holding the user-chosen default kernel version
DEFAULT_KERNEL_SETTING = "default_kernel_version"

# Same shape the cloakbrowser package accepts as a version pin:
# 4 or 5 dot-separated numeric components (e.g. "146.0.7680.177.5").
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")

_KERNEL_DIR_PREFIX = "chromium-"


class KernelError(Exception):
    """Base class for kernel management failures."""


class KernelSourceError(KernelError):
    """The import source is missing or does not contain a kernel."""


class KernelExistsError(KernelError):
    """A kernel with this version is already installed."""


class KernelVersionError(KernelError):
    """The version string is missing or malformed."""


class KernelNotFoundError(KernelError):
    """The requested kernel version is not installed."""


def _valid_version(version: str | None) -> bool:
    return bool(version) and _VERSION_RE.fullmatch(version) is not None


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _exe_relpath() -> Path:
    """Executable path inside a kernel dir (mirrors cloakbrowser's layout)."""
    system = platform.system()
    if system == "Windows":
        return Path("chrome.exe")
    if system == "Darwin":
        return Path("Chromium.app") / "Contents" / "MacOS" / "Chromium"
    return Path("chrome")


def _kernel_dir(version: str) -> Path:
    return effective_kernel_dir() / f"{_KERNEL_DIR_PREFIX}{version}"


def _kernel_exe(version: str) -> Path:
    return _kernel_dir(version) / _exe_relpath()


def _dir_size(path: Path) -> int | None:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return None


def _make_executable(path: Path) -> None:
    """chmod +x; skipped on Windows (no-op there, and AV can lock the file)."""
    if platform.system() == "Windows":
        return
    try:
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        logger.warning("Could not make %s executable", path)


def kernel_installed(version: str) -> bool:
    """True when a launchable kernel for this exact version is on disk."""
    return _valid_version(version) and _kernel_exe(version).is_file()


def _iter_kernel_dirs() -> list[tuple[str, Path]]:
    """(version, dir) pairs for launchable kernels in the storage dir.

    ``-pro`` suffixed dirs are skipped: the free ``browser_version`` pin path
    the manager uses never resolves them, so they would be unlaunchable.
    """
    root = effective_kernel_dir()
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(_KERNEL_DIR_PREFIX):
            continue
        version = entry.name[len(_KERNEL_DIR_PREFIX):]
        if version.endswith("-pro") or not _valid_version(version):
            continue
        if not (entry / _exe_relpath()).is_file():
            continue
        found.append((version, entry))
    found.sort(key=lambda pair: _version_tuple(pair[0]), reverse=True)
    return found


def any_kernel_installed() -> bool:
    """Cheap readiness probe (no size walk) — safe to call on every poll."""
    return bool(_iter_kernel_dirs())


def installed_versions() -> list[str]:
    """Installed kernel versions, newest first (no size walk)."""
    return [version for version, _ in _iter_kernel_dirs()]


def list_kernels() -> list[dict[str, Any]]:
    """Installed kernels with on-disk sizes, newest first (for the API/UI)."""
    return [
        {
            "version": version,
            "path": str(path),
            "size": _dir_size(path),
            "pro": False,
        }
        for version, path in _iter_kernel_dirs()
    ]


def get_default_version() -> str | None:
    """The user-chosen default version, or None if unset or no longer installed."""
    saved = db.get_setting(DEFAULT_KERNEL_SETTING)
    if saved and kernel_installed(saved):
        return saved
    return None


def set_default_version(version: str | None) -> None:
    """Persist the default kernel version; None clears the setting."""
    if version is None:
        db.set_setting(DEFAULT_KERNEL_SETTING, None)
        return
    if not _valid_version(version):
        raise KernelVersionError(f"Invalid kernel version: {version!r}")
    if not kernel_installed(version):
        raise KernelNotFoundError(f"Kernel {version} is not installed")
    db.set_setting(DEFAULT_KERNEL_SETTING, version)


def resolve_kernel_version(explicit: str | None) -> str | None:
    """Pick the version a launch should pin.

    Explicit (profile) choice must be installed; otherwise fall back to the
    default setting, then the newest installed kernel. None means no kernel
    is installed at all.
    """
    explicit = (explicit or "").strip() or None
    if explicit:
        if not _valid_version(explicit):
            raise ValueError(f"Invalid kernel version on profile: {explicit!r}")
        if not kernel_installed(explicit):
            raise ValueError(
                f"Kernel {explicit} is not installed. Import it in Settings → Browser kernels, "
                "or clear the profile's kernel selection."
            )
        return explicit
    default = get_default_version()
    if default:
        return default
    versions = installed_versions()
    return versions[0] if versions else None


def _safe_extract_zip(archive: Path, dest: Path) -> None:
    """Extract a zip with per-member path containment (no traversal)."""
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member_path = (dest / info.filename).resolve()
            if not member_path.is_relative_to(dest_resolved):
                raise KernelSourceError(
                    f"Archive contains an unsafe path: {info.filename}"
                )
        zf.extractall(dest)


def _flatten_single_subdir(dest: Path) -> None:
    """If extraction produced one wrapping directory, move its contents up.

    macOS .app bundles are never flattened — the bundle structure must stay.
    """
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].name.endswith(".app"):
        subdir = entries[0]
        for item in subdir.iterdir():
            shutil.move(str(item), str(dest / item.name))
        subdir.rmdir()


def _version_from_dir_name(path: Path) -> str | None:
    name = path.name
    if not name.startswith(_KERNEL_DIR_PREFIX):
        return None
    version = name[len(_KERNEL_DIR_PREFIX):]
    return version if _valid_version(version) else None


def _locate_kernel_root(src: Path) -> Path:
    """Find the directory that directly contains the kernel executable."""
    if (src / _exe_relpath()).is_file():
        return src
    candidates = [
        child
        for child in src.iterdir()
        if child.is_dir() and (child / _exe_relpath()).is_file()
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise KernelSourceError(
        f"No CloakBrowser kernel found in {src} "
        f"(expected {_exe_relpath()} inside it or exactly one subdirectory)"
    )


def import_kernel(source_path: str, version: str | None = None) -> dict[str, Any]:
    """Install a user-downloaded kernel (a .zip archive or an extracted folder)
    into the managed kernel storage directory.

    The version names the target directory (``chromium-<version>``) and is the
    string profiles pin at launch. It cannot be read from the binary (the exe
    only carries the 4-part Chromium version, releases use a 5-part string),
    so it must come from the caller or a ``chromium-<version>`` folder name.
    """
    src = Path(source_path)
    if not src.exists():
        raise KernelSourceError(f"Source not found: {src}")

    version = (version or "").strip() or None
    if version and not _valid_version(version):
        raise KernelVersionError(
            f"Invalid kernel version: {version!r}. Use the full numeric version "
            "from the release tag, e.g. 146.0.7680.177.5."
        )

    root = effective_kernel_dir()
    root.mkdir(parents=True, exist_ok=True)

    if src.is_file():
        if src.suffix.lower() != ".zip":
            raise KernelSourceError(
                f"Unsupported source file: {src.name} (expected a .zip archive or a folder)"
            )
        if not version:
            raise KernelVersionError(
                "Kernel version is required when importing an archive "
                "(see the release tag, e.g. chromium-v146.0.7680.177.5)."
            )
        target = _kernel_dir(version)
        if target.exists():
            raise KernelExistsError(f"Kernel {version} is already installed")
        staging = Path(tempfile.mkdtemp(prefix=".kernel-import-", dir=root))
        try:
            _safe_extract_zip(src, staging)
            _flatten_single_subdir(staging)
            exe = staging / _exe_relpath()
            if not exe.is_file():
                raise KernelSourceError(
                    "Archive does not contain a CloakBrowser kernel "
                    f"({_exe_relpath()} not found after extraction)"
                )
            _make_executable(exe)
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    else:
        kernel_root = _locate_kernel_root(src)
        if not version:
            version = _version_from_dir_name(kernel_root)
        if not version:
            raise KernelVersionError(
                "Kernel version is required: the folder name does not encode it "
                "(see the release tag, e.g. chromium-v146.0.7680.177.5)."
            )
        target = _kernel_dir(version)
        if kernel_root.resolve() == target.resolve():
            _make_executable(target / _exe_relpath())
            logger.info("Kernel %s already in place at %s", version, target)
            return {"version": version, "path": str(target), "size": _dir_size(target), "pro": False}
        if target.exists():
            raise KernelExistsError(f"Kernel {version} is already installed")
        if kernel_root.resolve().is_relative_to(root.resolve()):
            os.replace(kernel_root, target)
        else:
            shutil.copytree(kernel_root, target)
        _make_executable(target / _exe_relpath())

    logger.info("Imported kernel %s -> %s", version, target)
    return {"version": version, "path": str(target), "size": _dir_size(target), "pro": False}


def delete_kernel(version: str) -> None:
    """Remove an installed kernel; clears the default setting if it pointed here."""
    if not _valid_version(version):
        raise KernelVersionError(f"Invalid kernel version: {version!r}")
    root = effective_kernel_dir().resolve()
    target = _kernel_dir(version).resolve()
    if not target.is_relative_to(root):
        raise KernelVersionError(f"Kernel path escapes the storage directory: {target}")
    if not target.exists():
        raise KernelNotFoundError(f"Kernel {version} is not installed")
    shutil.rmtree(target)
    if db.get_setting(DEFAULT_KERNEL_SETTING) == version:
        db.set_setting(DEFAULT_KERNEL_SETTING, None)
    logger.info("Deleted kernel %s", version)
