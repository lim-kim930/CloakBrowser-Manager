# Kernel Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic kernel download with a user-managed kernel library: import existing kernel directories (referenced in place via junction/symlink), download the recommended version on demand, pick a kernel per profile with a global default.

**Architecture:** New `kernels` SQLite table + `backend/kernel_manager.py` (link creation, version detection, validation) + `backend/kernels_api.py` router. `binary_status.py` is reworked from "download tracker" to "kernel library status". Launch resolves the profile's kernel (or the default), validates the executable exists, and pins it via `browser_version=` — `ensure_binary` resolves `<cache>/chromium-{version}/` locally without network. Frontend gains a settings page, an empty-library banner, and a kernel dropdown in the profile form; bootstrap no longer blocks on kernel state.

**Tech Stack:** Python 3.12 / FastAPI / sqlite3 / pytest; React 19 + TypeScript + Vite + vitest; Tauri 2 (`tauri-plugin-dialog` added for the folder picker).

**Spec:** `docs/superpowers/specs/2026-07-13-kernel-management-design.md`

## Global Constraints

- Never bundle the CloakBrowser Chromium binary into any distributed artifact (`BINARY-LICENSE.md`).
- Conventional Commits; one commit per logical task.
- `backend/main.py` uses relative imports — always run as a package from repo root.
- Backend test command (repo root): `backend/.venv/Scripts/python.exe -m pytest -q`
- Frontend test command (in `frontend/`): `pnpm test`; type check: `pnpm build`
- Rust tests: `cargo test --manifest-path frontend/src-tauri/Cargo.toml`
- Imported kernels are NEVER copied and the user's original directory is NEVER deleted; deleting an `imported` kernel removes only the link + DB row. Deleting a `downloaded` kernel removes its cache directory.
- Launch must NEVER silently fall back to a different kernel than the profile's resolved one.

---

### Task 1: `kernels` table + DB CRUD + `profiles.kernel_id`

**Files:**
- Modify: `backend/database.py`
- Test: `backend/tests/test_database.py` (append)

**Interfaces:**
- Produces (used by Tasks 2–6):
  - `db.create_kernel(version: str, source: str, source_path: str | None = None) -> dict` — raises `sqlite3.IntegrityError` on duplicate version; first kernel ever becomes default.
  - `db.list_kernels() -> list[dict]` — each dict: `id, version, source, source_path, is_default (bool), profile_count (int), created_at`.
  - `db.get_kernel(kernel_id: str) -> dict | None`
  - `db.get_default_kernel() -> dict | None`
  - `db.set_default_kernel(kernel_id: str) -> bool`
  - `db.delete_kernel(kernel_id: str) -> bool` — reassigns default to another kernel if the default was deleted; referencing profiles get `kernel_id = NULL` (FK `ON DELETE SET NULL`).
  - `profiles` rows now contain `kernel_id: str | None`; `create_profile`/`update_profile` accept a `kernel_id` field.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_database.py`:

```python
# ── Kernels ───────────────────────────────────────────────────────────────────


class TestKernels:
    def test_create_first_kernel_becomes_default(self, tmp_db):
        k = db.create_kernel("146.0.7680.177.5", "downloaded")
        assert k["version"] == "146.0.7680.177.5"
        assert k["source"] == "downloaded"
        assert k["source_path"] is None
        assert k["is_default"] is True

    def test_second_kernel_not_default(self, tmp_db):
        db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "imported", source_path=r"D:\kernels\two")
        assert k2["is_default"] is False
        assert k2["source_path"] == r"D:\kernels\two"

    def test_duplicate_version_rejected(self, tmp_db):
        import sqlite3
        db.create_kernel("1.0.0.0", "downloaded")
        with pytest.raises(sqlite3.IntegrityError):
            db.create_kernel("1.0.0.0", "imported", source_path="x")

    def test_list_kernels_profile_count(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        db.create_profile(name="P1", kernel_id=k["id"])
        db.create_profile(name="P2", kernel_id=k["id"])
        db.create_profile(name="P3")  # follows default, does not count as reference
        kernels = db.list_kernels()
        assert len(kernels) == 1
        assert kernels[0]["profile_count"] == 2

    def test_set_default_kernel_moves_flag(self, tmp_db):
        k1 = db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "downloaded")
        assert db.set_default_kernel(k2["id"]) is True
        assert db.get_default_kernel()["id"] == k2["id"]
        assert db.get_kernel(k1["id"])["is_default"] is False

    def test_set_default_unknown_id(self, tmp_db):
        assert db.set_default_kernel("nope") is False

    def test_delete_kernel_reassigns_default(self, tmp_db):
        k1 = db.create_kernel("1.0.0.0", "downloaded")
        k2 = db.create_kernel("2.0.0.0", "downloaded")
        assert db.delete_kernel(k1["id"]) is True
        assert db.get_default_kernel()["id"] == k2["id"]

    def test_delete_kernel_nulls_profile_reference(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        p = db.create_profile(name="P", kernel_id=k["id"])
        db.delete_kernel(k["id"])
        assert db.get_profile(p["id"])["kernel_id"] is None

    def test_profile_kernel_id_roundtrip(self, tmp_db):
        k = db.create_kernel("1.0.0.0", "downloaded")
        p = db.create_profile(name="P", kernel_id=k["id"])
        assert p["kernel_id"] == k["id"]
        p2 = db.update_profile(p["id"], kernel_id=None)
        assert p2["kernel_id"] is None
```

If `test_database.py` doesn't already import `pytest`/`db`, add at the top of the appended block: `import pytest` and `from backend import database as db` (match the file's existing imports — reuse them if present).

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_database.py -k Kernels -q`
Expected: FAIL — `AttributeError: module 'backend.database' has no attribute 'create_kernel'`

- [ ] **Step 3: Implement**

In `backend/database.py`:

3a. In `init_db()`, inside the `executescript` string add after `profile_tags`:

```sql
CREATE TABLE IF NOT EXISTS kernels (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_path TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
```

and add `kernel_id TEXT REFERENCES kernels(id) ON DELETE SET NULL,` to the `CREATE TABLE IF NOT EXISTS profiles` column list (after `user_data_dir TEXT NOT NULL,`). In the migrations block below, add:

```python
        if "kernel_id" not in cols:
            conn.execute(
                "ALTER TABLE profiles ADD COLUMN kernel_id TEXT "
                "REFERENCES kernels(id) ON DELETE SET NULL"
            )
            conn.commit()
```

3b. In `create_profile`, add `fields.get("kernel_id"),` to the INSERT: add `kernel_id` to the column list (after `user_data_dir`? No — keep order: add `kernel_id` between `user_data_dir` and `created_at` in both column list and VALUES tuple, with one more `?`).

3c. In `update_profile`, add `"kernel_id"` to the tuple of updatable columns.

3d. Append kernel CRUD at the end of the file:

```python
# ── Kernels ───────────────────────────────────────────────────────────────────


def _kernel_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    kernel = dict(row)
    kernel["is_default"] = bool(kernel["is_default"])
    count = conn.execute(
        "SELECT COUNT(*) FROM profiles WHERE kernel_id = ?", (kernel["id"],)
    ).fetchone()[0]
    kernel["profile_count"] = count
    return kernel


def create_kernel(version: str, source: str, source_path: str | None = None) -> dict[str, Any]:
    _ensure_configured()
    kernel_id = str(uuid.uuid4())
    with get_db() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM kernels").fetchone()[0]
        conn.execute(
            "INSERT INTO kernels (id, version, source, source_path, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kernel_id, version, source, source_path, 1 if existing == 0 else 0, _now()),
        )
        conn.commit()
    return get_kernel(kernel_id)  # type: ignore[return-value]


def get_kernel(kernel_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM kernels WHERE id = ?", (kernel_id,)).fetchone()
        return _kernel_row(conn, row) if row else None


def get_kernel_by_version(version: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM kernels WHERE version = ?", (version,)).fetchone()
        return _kernel_row(conn, row) if row else None


def get_default_kernel() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM kernels WHERE is_default = 1").fetchone()
        return _kernel_row(conn, row) if row else None


def list_kernels() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM kernels ORDER BY created_at").fetchall()
        return [_kernel_row(conn, row) for row in rows]


def set_default_kernel(kernel_id: str) -> bool:
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM kernels WHERE id = ?", (kernel_id,)).fetchone()
        if not exists:
            return False
        conn.execute("UPDATE kernels SET is_default = 0")
        conn.execute("UPDATE kernels SET is_default = 1 WHERE id = ?", (kernel_id,))
        conn.commit()
        return True


def delete_kernel(kernel_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_default FROM kernels WHERE id = ?", (kernel_id,)).fetchone()
        if not row:
            return False
        was_default = bool(row["is_default"])
        conn.execute("DELETE FROM kernels WHERE id = ?", (kernel_id,))
        if was_default:
            remaining = conn.execute(
                "SELECT id FROM kernels ORDER BY created_at LIMIT 1"
            ).fetchone()
            if remaining:
                conn.execute("UPDATE kernels SET is_default = 1 WHERE id = ?", (remaining["id"],))
        conn.commit()
        return True
```

Also export `get_kernel_by_version` for Task 3's duplicate check (already in the code above).

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_database.py -q`
Expected: PASS (all, including pre-existing tests)

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_database.py
git commit -m "feat(backend): kernels table, kernel CRUD, profiles.kernel_id"
```

---

### Task 2: `kernel_manager.py` — links, version detection, import/remove

**Files:**
- Create: `backend/kernel_manager.py`
- Test: `backend/tests/test_kernel_manager.py`

**Interfaces:**
- Consumes: `db.create_kernel`, `db.get_kernel_by_version` (Task 1).
- Produces (used by Tasks 3–6):
  - `class KernelImportError(ValueError)` — message is user-facing.
  - `cache_dir() -> Path` — `CLOAKBROWSER_CACHE_DIR` env or `~/.cloakbrowser`.
  - `exe_relpath() -> Path` — platform executable relative path.
  - `kernel_exe(version: str) -> Path` — `<cache>/chromium-{version}/<exe_relpath>`.
  - `kernel_is_valid(version: str) -> bool`
  - `detect_version(directory: Path) -> str` — raises `KernelImportError`.
  - `import_kernel(directory: str) -> dict` — full import flow, returns the DB kernel dict; raises `KernelImportError`.
  - `remove_kernel_files(kernel: dict) -> None` — imported: remove link only; downloaded: `shutil.rmtree` the cache dir.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_kernel_manager.py`:

```python
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


class TestValidity:
    def test_valid_and_invalid(self, cache, tmp_db, tmp_path):
        d = make_kernel_dir(tmp_path, "chromium-1.2.3.4")
        km.import_kernel(str(d))
        assert km.kernel_is_valid("1.2.3.4") is True
        # User deletes their original directory → link dangles
        import shutil
        shutil.rmtree(d)
        assert km.kernel_is_valid("1.2.3.4") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_kernel_manager.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.kernel_manager'` (import error at collection)

- [ ] **Step 3: Implement**

Create `backend/kernel_manager.py`:

```python
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


def create_link(version: str, target: Path) -> None:
    """Create <cache>/chromium-{version} pointing at target. Replaces a stale link."""
    link = kernel_dir(version)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
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
    create_link(version, target)
    return db.create_kernel(version, "imported", source_path=str(target))


def remove_kernel_files(kernel: dict) -> None:
    d = kernel_dir(kernel["version"])
    if not (d.exists() or d.is_symlink()):
        return
    if kernel["source"] == "imported":
        _remove_link(d)
    else:
        shutil.rmtree(d, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_kernel_manager.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/kernel_manager.py backend/tests/test_kernel_manager.py
git commit -m "feat(backend): kernel_manager — import via junction/symlink, version detection"
```

---

### Task 3: Rework `binary_status.py` into kernel-library status + download runner

**Files:**
- Rewrite: `backend/binary_status.py`
- Rewrite: `backend/tests/test_binary_status.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `db.list_kernels`, `db.get_default_kernel`, `db.get_kernel_by_version`, `db.create_kernel` (Task 1); `kernel_manager` not needed here.
- Produces (used by Tasks 4–6 and health endpoint):
  - `library_snapshot() -> dict` — `{"state": "none"|"downloading"|"ready"|"error", "version": str|None, "error": str|None}`. Priority: downloading > (any kernel → ready, version = default's) > (last download failed → error) > none.
  - `download.snapshot() -> dict` — `{"state": "idle"|"downloading"|"ready"|"error", "error": str|None}`.
  - `download.start() -> bool` — spawns the download thread; `False` if one is already running.
  - `DownloadTracker` class (module singleton `download`).
  - Conftest fixture `installed_kernel` replaces `kernel_ready`.

- [ ] **Step 1: Rewrite tests**

Replace the contents of `backend/tests/test_binary_status.py`:

```python
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
```

- [ ] **Step 2: Update conftest**

In `backend/tests/conftest.py`:
- Delete the `kernel_ready` fixture.
- Add:

```python
@pytest.fixture()
def installed_kernel(tmp_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Register a valid kernel: cache dir + fake exe + DB row (default)."""
    from backend import kernel_manager as km

    cache = tmp_path / "kernel-cache"
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(cache))
    exe = km.kernel_exe("1.0.0.0")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake")
    return db.create_kernel("1.0.0.0", "downloaded")
```

- In `app_client`, replace the `kernel_ready` parameter with `installed_kernel`, and replace `monkeypatch.setattr(binary_status, "start_background_ensure", lambda: None)` with nothing (the function is being deleted; remove the line).

- [ ] **Step 3: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_status.py -q`
Expected: FAIL — `AttributeError: module 'backend.binary_status' has no attribute 'library_snapshot'`

- [ ] **Step 4: Rewrite `backend/binary_status.py`**

```python
"""Kernel library status for /api/health + on-demand download runner.

The library state is derived from the kernels table; the only mutable piece
is the download tracker (user-triggered, one at a time).
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Callable, Literal

from . import database as db

logger = logging.getLogger("cloakbrowser.manager.binary")

LibraryState = Literal["none", "downloading", "ready", "error"]
DownloadState = Literal["idle", "downloading", "ready", "error"]


class DownloadTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: DownloadState = "idle"
        self._error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "error": self._error}

    def _set(self, state: DownloadState, error: str | None) -> None:
        with self._lock:
            self._state = state
            self._error = error

    def start(self) -> bool:
        """Kick off the recommended-version download in a daemon thread.

        Returns False if a download is already running.
        """
        with self._lock:
            if self._state == "downloading":
                return False
            self._state = "downloading"
            self._error = None
        threading.Thread(
            target=run_download, args=(self, _ensure_recommended),
            name="kernel-download", daemon=True,
        ).start()
        return True


download = DownloadTracker()


def _ensure_recommended() -> str:
    from cloakbrowser.download import ensure_binary

    return str(ensure_binary())


def run_download(tracker: DownloadTracker, ensure_fn: Callable[[], str]) -> None:
    """Download the recommended kernel and register it. Blocking — run in a thread."""
    tracker._set("downloading", None)
    try:
        exe_path = ensure_fn()
    except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
        logger.error("Kernel download failed: %s", exc)
        tracker._set("error", str(exc))
        return
    version = _version_from_exe_path(exe_path)
    if version is None:
        tracker._set("error", f"Downloaded kernel has unexpected path layout: {exe_path}")
        return
    if not db.get_kernel_by_version(version):
        db.create_kernel(version, "downloaded")
    tracker._set("ready", None)
    logger.info("Kernel %s downloaded and registered", version)


def _version_from_exe_path(exe_path: str) -> str | None:
    """Extract the version from .../chromium-{version}[...]/<exe>."""
    for part in reversed(Path(exe_path).parts):
        m = re.fullmatch(r"chromium-(\d+(?:\.\d+){2,4})(?:-pro)?", part)
        if m:
            return m.group(1)
    return None


def library_snapshot() -> dict:
    """State of the kernel library, for /api/health."""
    dl = download.snapshot()
    if dl["state"] == "downloading":
        return {"state": "downloading", "version": None, "error": None}
    kernels = db.list_kernels()
    if kernels:
        default = db.get_default_kernel()
        version = default["version"] if default else kernels[0]["version"]
        return {"state": "ready", "version": version, "error": None}
    if dl["state"] == "error":
        return {"state": "error", "version": None, "error": dl["error"]}
    return {"state": "none", "version": None, "error": None}
```

(The old `BinaryStatusTracker`, `tracker`, `run_ensure_binary`, `_ensure_kernel`, `_kernel_version`, `start_background_ensure` are deleted. Tasks 4–5 fix the remaining references in `main.py` / `browser_manager.py` — until then the full suite will fail; that's expected mid-refactor. Run only the targeted files in this task.)

- [ ] **Step 5: Run targeted tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_status.py backend/tests/test_kernel_manager.py backend/tests/test_database.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/binary_status.py backend/tests/test_binary_status.py backend/tests/conftest.py
git commit -m "feat(backend)!: binary_status reports kernel-library state; on-demand download"
```

---

### Task 4: Launch resolution + `main.py` integration (lifespan, health, status)

**Files:**
- Modify: `backend/browser_manager.py`
- Modify: `backend/main.py`
- Modify: `backend/models.py`
- Modify: `backend/tests/test_browser_manager.py`, `backend/tests/test_api.py` (fix fixture usage + add cases)

**Interfaces:**
- Consumes: `db.get_kernel`, `db.get_default_kernel` (Task 1); `kernel_manager.kernel_is_valid` (Task 2); `binary_status.library_snapshot` (Task 3).
- Produces:
  - `browser_manager.KernelNotConfiguredError(RuntimeError)` — no kernel in library / profile's kernel row missing → HTTP 503 `"no_kernel"`.
  - `browser_manager.KernelInvalidError(RuntimeError)` — kernel files missing on disk → HTTP 409, message names the version.
  - `BrowserManager._resolve_kernel(profile: dict) -> dict` — returns the kernel row.
  - `launch()` passes `browser_version=kernel["version"]`.
  - `models.BinaryStatus.state` gains `"none"`; `ProfileCreate/ProfileUpdate/ProfileResponse` gain `kernel_id: str | None`; `StatusResponse.binary_version: str | None`.
  - `BinaryNotReadyError` is deleted.

- [ ] **Step 1: Write failing tests**

In `backend/tests/test_browser_manager.py`, add (reusing that file's existing imports/fixtures — it already imports `BrowserManager`; update its import line to `from backend.browser_manager import BrowserManager, KernelInvalidError, KernelNotConfiguredError` and remove `BinaryNotReadyError` references; delete/rewrite any test that asserted `BinaryNotReadyError`):

```python
class TestKernelResolution:
    async def test_launch_no_kernel_raises(self, tmp_db):
        mgr = BrowserManager()
        profile = db.create_profile(name="P")
        with pytest.raises(KernelNotConfiguredError):
            await mgr.launch(profile)

    async def test_launch_invalid_kernel_raises(self, tmp_db, installed_kernel):
        import shutil
        from backend import kernel_manager as km
        shutil.rmtree(km.kernel_dir("1.0.0.0"))  # kernel files vanish
        mgr = BrowserManager()
        profile = db.create_profile(name="P")
        with pytest.raises(KernelInvalidError, match="1.0.0.0"):
            await mgr.launch(profile)

    async def test_launch_pins_browser_version(self, tmp_db, installed_kernel):
        import cloakbrowser
        mgr = BrowserManager()
        profile = db.create_profile(name="P")
        await mgr.launch(profile)
        kwargs = cloakbrowser.launch_persistent_context_async.call_args.kwargs
        assert kwargs["browser_version"] == "1.0.0.0"

    async def test_launch_profile_kernel_overrides_default(self, tmp_db, installed_kernel, tmp_path):
        import cloakbrowser
        from backend import kernel_manager as km
        exe = km.kernel_exe("2.0.0.0")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        k2 = db.create_kernel("2.0.0.0", "downloaded")
        mgr = BrowserManager()
        profile = db.create_profile(name="P", kernel_id=k2["id"])
        await mgr.launch(profile)
        kwargs = cloakbrowser.launch_persistent_context_async.call_args.kwargs
        assert kwargs["browser_version"] == "2.0.0.0"
```

(If the mocked `launch_persistent_context_async` return value needs `.on`, the existing tests already handle that — follow the same AsyncMock configuration they use.)

In `backend/tests/test_api.py` add:

```python
class TestLaunchKernelErrors:
    def test_launch_without_kernel_503(self, tmp_db, monkeypatch):
        """app_client includes installed_kernel; build a bare client instead."""
        from unittest.mock import AsyncMock
        from starlette.testclient import TestClient
        from backend import main

        monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
        with TestClient(main.app) as client:
            p = client.post("/api/profiles", json={"name": "P"}).json()
            resp = client.post(f"/api/profiles/{p['id']}/launch")
            assert resp.status_code == 503
            assert resp.json()["detail"] == "no_kernel"

    def test_health_reports_none_when_empty(self, tmp_db, monkeypatch):
        from unittest.mock import AsyncMock
        from starlette.testclient import TestClient
        from backend import main

        monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
        with TestClient(main.app) as client:
            body = client.get("/api/health").json()
            assert body["binary"]["state"] == "none"

    def test_health_ready_with_kernel(self, app_client):
        body = app_client.get("/api/health").json()
        assert body["binary"]["state"] == "ready"
        assert body["binary"]["version"] == "1.0.0.0"
```

Also fix any existing tests referencing `kernel_ready` → `installed_kernel`, and any asserting `binary_version == "0.0.0-test"` in `/api/status` → expect `"1.0.0.0"` (via `app_client`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_browser_manager.py backend/tests/test_api.py -q`
Expected: FAIL (ImportError on `KernelNotConfiguredError`, etc.)

- [ ] **Step 3: Implement**

`backend/browser_manager.py`:

3a. Replace `BinaryNotReadyError` with:

```python
class KernelNotConfiguredError(RuntimeError):
    """No kernel in the library (or the profile's kernel row is gone)."""


class KernelInvalidError(RuntimeError):
    """The kernel's files are missing on disk (moved/deleted by the user)."""
```

3b. Change the import at the top: `from . import binary_status` → `from . import database as db, kernel_manager`. (Note: `auto_launch_all` currently re-imports db locally — remove that local import.)

3c. Add to `BrowserManager`:

```python
    def _resolve_kernel(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Profile's kernel, falling back to the default. Validates files exist."""
        kernel = None
        if profile.get("kernel_id"):
            kernel = db.get_kernel(profile["kernel_id"])
        if kernel is None:
            kernel = db.get_default_kernel()
        if kernel is None:
            raise KernelNotConfiguredError("No browser kernel configured")
        if not kernel_manager.kernel_is_valid(kernel["version"]):
            raise KernelInvalidError(
                f"Kernel {kernel['version']} is missing on disk — "
                f"manage kernels in Settings"
            )
        return kernel
```

3d. In `launch()`: replace the `binary_status.tracker` gate at the top with `kernel = self._resolve_kernel(profile)` and add `browser_version=kernel["version"],` to the `launch_persistent_context_async(...)` call.

3e. Replace the kernel-wait loop in `auto_launch_all()` (the `while True: state = binary_status...` block) with:

```python
        if db.get_default_kernel() is None:
            logger.info("Auto-launch skipped: no kernel configured")
            return
```

`backend/models.py`:
- `BinaryStatus.state: Literal["none", "downloading", "ready", "error"]`
- `StatusResponse.binary_version: str | None`
- Add `kernel_id: str | None = None` to `ProfileCreate`, `ProfileUpdate` (as `Field(default=None)` like other nullable update fields), and `ProfileResponse`.

`backend/main.py`:
- Import fixes: `from .browser_manager import BrowserManager, KernelInvalidError, KernelNotConfiguredError` (drop `BinaryNotReadyError`).
- Lifespan: delete the `binary_status.start_background_ensure()` line.
- `launch_profile` exception mapping:

```python
    except KernelNotConfiguredError:
        raise HTTPException(status_code=503, detail="no_kernel")
    except KernelInvalidError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
```

- `health()`: `binary=BinaryStatus(**binary_status.library_snapshot())`.
- `get_system_status()`: remove the `CHROMIUM_VERSION` import; use:

```python
    default = db.get_default_kernel()
    return StatusResponse(
        running_count=len(browser_mgr.running),
        binary_version=default["version"] if default else None,
        profiles_total=len(profiles),
    )
```

- [ ] **Step 4: Run the FULL backend suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (this task repairs everything Task 3 broke; fix any straggler tests that still reference removed symbols — e.g. `test_entry.py` if it asserts `start_background_ensure`)

- [ ] **Step 5: Commit**

```bash
git add backend/browser_manager.py backend/main.py backend/models.py backend/tests/
git commit -m "feat(backend)!: per-profile kernel resolution; no auto-download on startup"
```

---

### Task 5: Kernels REST API

**Files:**
- Create: `backend/kernels_api.py`
- Modify: `backend/main.py` (include router), `backend/models.py` (kernel models)
- Test: `backend/tests/test_kernels_api.py`

**Interfaces:**
- Consumes: Tasks 1–4 symbols.
- Produces (consumed by frontend Task 7):
  - `GET /api/kernels` → `[{id, version, source, source_path, is_default, valid, profile_count, created_at}]`
  - `POST /api/kernels/import` body `{"path": str}` → kernel object; 400 with `KernelImportError` message on failure.
  - `POST /api/kernels/download` → `{"ok": true}`; 409 if already downloading.
  - `GET /api/kernels/download/status` → `{"state": "idle"|"downloading"|"ready"|"error", "error": str|null}`
  - `PUT /api/kernels/{id}/default` → `{"ok": true}`; 404 unknown id.
  - `DELETE /api/kernels/{id}` → `{"ok": true}`; 404 unknown; 409 if a running profile resolves to it.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_kernels_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_kernels_api.py -q`
Expected: FAIL — 404s (routes don't exist)

- [ ] **Step 3: Implement**

Add to `backend/models.py`:

```python
class KernelResponse(BaseModel):
    id: str
    version: str
    source: Literal["imported", "downloaded"]
    source_path: str | None = None
    is_default: bool
    valid: bool
    profile_count: int
    created_at: str


class KernelImportRequest(BaseModel):
    path: str


class DownloadStatusResponse(BaseModel):
    state: Literal["idle", "downloading", "ready", "error"]
    error: str | None = None
```

Create `backend/kernels_api.py`:

```python
"""REST endpoints for the kernel library."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from . import binary_status, database as db, kernel_manager
from .models import DownloadStatusResponse, KernelImportRequest, KernelResponse

logger = logging.getLogger("cloakbrowser.manager.kernels")

router = APIRouter(prefix="/api/kernels")


def _to_response(kernel: dict) -> KernelResponse:
    return KernelResponse(
        **kernel, valid=kernel_manager.kernel_is_valid(kernel["version"])
    )


@router.get("", response_model=list[KernelResponse])
async def list_kernels():
    return [_to_response(k) for k in db.list_kernels()]


@router.post("/import", response_model=KernelResponse, status_code=201)
async def import_kernel(req: KernelImportRequest):
    try:
        kernel = kernel_manager.import_kernel(req.path)
    except kernel_manager.KernelImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Imported kernel %s from %s", kernel["version"], req.path)
    return _to_response(kernel)


@router.post("/download")
async def download_kernel():
    if not binary_status.download.start():
        raise HTTPException(status_code=409, detail="A download is already in progress")
    return {"ok": True}


@router.get("/download/status", response_model=DownloadStatusResponse)
async def download_status():
    return DownloadStatusResponse(**binary_status.download.snapshot())


@router.put("/{kernel_id}/default")
async def set_default(kernel_id: str):
    if not db.set_default_kernel(kernel_id):
        raise HTTPException(status_code=404, detail="Kernel not found")
    return {"ok": True}


def _kernel_in_use(kernel_id: str) -> bool:
    """True if any currently running profile resolves to this kernel."""
    from .main import browser_mgr  # late import — main imports this module

    default = db.get_default_kernel()
    for profile_id in list(browser_mgr.running):
        profile = db.get_profile(profile_id)
        if profile is None:
            continue
        effective = profile.get("kernel_id") or (default["id"] if default else None)
        if effective == kernel_id:
            return True
    return False


@router.delete("/{kernel_id}")
async def delete_kernel(kernel_id: str):
    kernel = db.get_kernel(kernel_id)
    if not kernel:
        raise HTTPException(status_code=404, detail="Kernel not found")
    if _kernel_in_use(kernel_id):
        raise HTTPException(
            status_code=409, detail="Kernel is in use by a running profile"
        )
    db.delete_kernel(kernel_id)
    kernel_manager.remove_kernel_files(kernel)
    return {"ok": True}
```

In `backend/main.py`, after `app = FastAPI(...)` middleware setup add:

```python
from .kernels_api import router as kernels_router  # noqa: E402 — needs app context

app.include_router(kernels_router)
```

(Place the import at the top with the other relative imports instead if no circularity arises — it doesn't: `kernels_api` only imports `main` lazily inside `_kernel_in_use`.)

- [ ] **Step 4: Run the full backend suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/kernels_api.py backend/models.py backend/main.py backend/tests/test_kernels_api.py
git commit -m "feat(backend): /api/kernels — list, import, download, default, delete"
```

---

### Task 6: Frontend API client + `useKernels` hook

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useKernels.ts`
- Test: `frontend/src/lib/api.test.ts` (append), `frontend/src/hooks/useKernels.test.ts`

**Interfaces:**
- Consumes: Task 5 endpoints.
- Produces (used by Tasks 8–10):
  - `interface Kernel { id; version; source: "imported" | "downloaded"; source_path: string | null; is_default: boolean; valid: boolean; profile_count: number; created_at: string }`
  - `interface DownloadStatus { state: "idle" | "downloading" | "ready" | "error"; error: string | null }`
  - `api.listKernels(): Promise<Kernel[]>`, `api.importKernel(path: string)`, `api.downloadKernel()`, `api.downloadStatus()`, `api.setDefaultKernel(id)`, `api.deleteKernel(id)`
  - `BinaryStatus.state` includes `"none"`; `Profile`/`ProfileCreateData` gain `kernel_id`.
  - `useKernels()` → `{ kernels, loading, error, downloadState, refresh, importKernel, startDownload, setDefault, remove }`. `importKernel`/`remove`/`setDefault` refresh the list; `startDownload` begins polling `downloadStatus` every 1s until `ready`/`error`, then refreshes.

- [ ] **Step 1: Write failing tests**

Append to `frontend/src/lib/api.test.ts` (match its existing fetch-mock pattern — read the file first and follow it exactly; the shape below assumes a `vi.stubGlobal("fetch", ...)` style):

```typescript
describe("kernel endpoints", () => {
  it("listKernels GETs /api/kernels", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson([]));
    vi.stubGlobal("fetch", fetchMock);
    await api.listKernels();
    expect(fetchMock).toHaveBeenCalledWith("/api/kernels", expect.anything());
  });

  it("importKernel POSTs path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ id: "k1" }));
    vi.stubGlobal("fetch", fetchMock);
    await api.importKernel("D:\\kernels\\chromium-1.0.0.0");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/kernels/import");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).path).toBe("D:\\kernels\\chromium-1.0.0.0");
  });

  it("setDefaultKernel PUTs /default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api.setDefaultKernel("k1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/kernels/k1/default");
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
  });

  it("deleteKernel DELETEs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api.deleteKernel("k1");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });
});
```

(`okJson` = whatever helper the file already uses to build a `Response`; if none exists, add `const okJson = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });`.)

Create `frontend/src/hooks/useKernels.test.ts`:

```typescript
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useKernels } from "./useKernels";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    listKernels: vi.fn(),
    importKernel: vi.fn(),
    downloadKernel: vi.fn(),
    downloadStatus: vi.fn(),
    setDefaultKernel: vi.fn(),
    deleteKernel: vi.fn(),
  },
}));

const kernel = {
  id: "k1", version: "1.0.0.0", source: "downloaded" as const, source_path: null,
  is_default: true, valid: true, profile_count: 0, created_at: "2026-01-01",
};

beforeEach(() => {
  vi.mocked(api.listKernels).mockResolvedValue([kernel]);
});

describe("useKernels", () => {
  it("loads kernels on mount", async () => {
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.kernels).toEqual([kernel]);
  });

  it("importKernel calls api and refreshes", async () => {
    vi.mocked(api.importKernel).mockResolvedValue(kernel);
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.importKernel("D:\\k"));
    expect(api.importKernel).toHaveBeenCalledWith("D:\\k");
    expect(api.listKernels).toHaveBeenCalledTimes(2);
  });

  it("importKernel surfaces API error message", async () => {
    vi.mocked(api.importKernel).mockRejectedValue(new Error("Not a directory: D:\\k"));
    const { result } = renderHook(() => useKernels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.importKernel("D:\\k"));
    expect(result.current.error).toContain("Not a directory");
  });

  it("startDownload polls status until ready then refreshes", async () => {
    vi.useFakeTimers();
    vi.mocked(api.downloadKernel).mockResolvedValue({ ok: true });
    vi.mocked(api.downloadStatus)
      .mockResolvedValueOnce({ state: "downloading", error: null })
      .mockResolvedValue({ state: "ready", error: null });
    const { result } = renderHook(() => useKernels());
    await act(async () => { await vi.runOnlyPendingTimersAsync(); });
    await act(() => result.current.startDownload());
    expect(result.current.downloadState.state).toBe("downloading");
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(result.current.downloadState.state).toBe("ready");
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/lib/api.test.ts src/hooks/useKernels.test.ts`
Expected: FAIL (missing exports / module)

- [ ] **Step 3: Implement**

`frontend/src/lib/api.ts` — change `BinaryStatus`:

```typescript
export interface BinaryStatus {
  state: "none" | "downloading" | "ready" | "error";
  version: string | null;
  error: string | null;
}
```

Add `kernel_id: string | null;` to `Profile` and `kernel_id?: string | null;` to `ProfileCreateData`. Add types + methods:

```typescript
export interface Kernel {
  id: string;
  version: string;
  source: "imported" | "downloaded";
  source_path: string | null;
  is_default: boolean;
  valid: boolean;
  profile_count: number;
  created_at: string;
}

export interface DownloadStatus {
  state: "idle" | "downloading" | "ready" | "error";
  error: string | null;
}
```

and inside `export const api = { ... }`:

```typescript
  listKernels: () => request<Kernel[]>("/api/kernels"),

  importKernel: (path: string) =>
    request<Kernel>("/api/kernels/import", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  downloadKernel: () =>
    request<{ ok: boolean }>("/api/kernels/download", { method: "POST" }),

  downloadStatus: () => request<DownloadStatus>("/api/kernels/download/status"),

  setDefaultKernel: (id: string) =>
    request<{ ok: boolean }>(`/api/kernels/${id}/default`, { method: "PUT" }),

  deleteKernel: (id: string) =>
    request<{ ok: boolean }>(`/api/kernels/${id}`, { method: "DELETE" }),
```

Create `frontend/src/hooks/useKernels.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DownloadStatus, type Kernel } from "../lib/api";

const DOWNLOAD_POLL_MS = 1000;

export function useKernels() {
  const [kernels, setKernels] = useState<Kernel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadState, setDownloadState] = useState<DownloadStatus>({
    state: "idle",
    error: null,
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setKernels(await api.listKernels());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load kernels");
    } finally {
      setLoading(false);
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    void refresh();
    return stopPolling;
  }, [refresh, stopPolling]);

  const startDownload = useCallback(async () => {
    try {
      await api.downloadKernel();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed to start");
      return;
    }
    setDownloadState({ state: "downloading", error: null });
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.downloadStatus();
        setDownloadState(status);
        if (status.state === "ready" || status.state === "error") {
          stopPolling();
          void refresh();
        }
      } catch {
        // transient — keep polling
      }
    }, DOWNLOAD_POLL_MS);
  }, [refresh, stopPolling]);

  const importKernel = useCallback(async (path: string) => {
    try {
      await api.importKernel(path);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
    await refresh();
  }, [refresh]);

  const setDefault = useCallback(async (id: string) => {
    try {
      await api.setDefaultKernel(id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set default");
    }
    await refresh();
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    try {
      await api.deleteKernel(id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
    await refresh();
  }, [refresh]);

  return { kernels, loading, error, downloadState, refresh, importKernel, startDownload, setDefault, remove };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/lib/api.test.ts src/hooks/useKernels.test.ts`
Expected: PASS. Then `pnpm build` — expect type check clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useKernels.ts frontend/src/lib/api.test.ts frontend/src/hooks/useKernels.test.ts
git commit -m "feat(frontend): kernel API client and useKernels hook"
```

---

### Task 7: Bootstrap no longer gates on kernel state

**Files:**
- Modify: `frontend/src/bootstrap/useBootstrap.ts`
- Modify: `frontend/src/App.tsx` (remove `downloading-binary` case only — the settings navigation is Task 9)
- Test: modify `frontend/src/bootstrap/useBootstrap.test.ts` if it exists (check with `ls frontend/src/bootstrap/`); otherwise cover via the changed union type + `pnpm build`

**Interfaces:**
- Produces: `BootstrapPhase` union loses `{ phase: "downloading-binary" }`. Health polling: any successful `api.health()` → `ready` (backend liveness only). `backend-error` remains for backend/Rust-shell failures only.

- [ ] **Step 1: Update `useBootstrap.ts`**

Remove `| { phase: "downloading-binary" }` from `BootstrapPhase`. Replace the body of `tick` in `startHealthPolling`:

```typescript
    const tick = async () => {
      try {
        await api.health();
        stopPolling();
        setState({ phase: "ready" });
      } catch {
        // transient — keep polling; the Rust shell reports hard failures
      }
    };
```

- [ ] **Step 2: Update `App.tsx`**

Delete the `case "downloading-binary":` branch.

- [ ] **Step 3: Update/verify tests**

If `frontend/src/bootstrap/` contains a test file asserting `downloading-binary`, update those assertions: a health response with `binary.state: "downloading"` (or `"none"`) must now yield `phase: "ready"`. Then:

Run (in `frontend/`): `pnpm test && pnpm build`
Expected: PASS, type check clean

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend)!: bootstrap gates on backend liveness only, not kernel state"
```

---

### Task 8: Tauri dialog plugin (folder picker)

**Files:**
- Modify: `frontend/src-tauri/Cargo.toml`, `frontend/src-tauri/src/lib.rs`, `frontend/src-tauri/capabilities/default.json`, `frontend/package.json` (via pnpm)
- Create: `frontend/src/lib/pickFolder.ts`

**Interfaces:**
- Produces: `pickFolder(): Promise<string | null>` — native folder dialog under Tauri, `window.prompt` fallback in plain web dev. Used by Task 9.

- [ ] **Step 1: Install the plugin**

```bash
cd frontend && pnpm add @tauri-apps/plugin-dialog
cargo add tauri-plugin-dialog --manifest-path src-tauri/Cargo.toml
```

- [ ] **Step 2: Register in Rust + capability**

In `frontend/src-tauri/src/lib.rs`, find the `tauri::Builder` chain and add `.plugin(tauri_plugin_dialog::init())` alongside the existing `.plugin(...)`/`.setup(...)` calls.

In `frontend/src-tauri/capabilities/default.json`, extend permissions:

```json
  "permissions": ["core:default", "dialog:default"]
```

- [ ] **Step 3: Create the wrapper**

`frontend/src/lib/pickFolder.ts`:

```typescript
import { isTauri } from "../bootstrap/tauri";

/** Native folder picker under Tauri; plain-text prompt in web dev. */
export async function pickFolder(): Promise<string | null> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  }
  return window.prompt("Kernel directory path:") ?? null;
}
```

(Check `frontend/src/bootstrap/tauri.ts` exports `isTauri` — it does, `useBootstrap` imports it.)

- [ ] **Step 4: Verify builds**

Run: `cargo test --manifest-path frontend/src-tauri/Cargo.toml` — expect PASS.
Run (in `frontend/`): `pnpm build` — expect clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src-tauri frontend/src/lib/pickFolder.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat(shell): add tauri-plugin-dialog for kernel folder picker"
```

---

### Task 9: Settings page + navigation + empty-library banner

**Files:**
- Create: `frontend/src/components/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `useKernels()` (Task 6), `pickFolder()` (Task 8).
- Produces: `<SettingsPage kernels={...} />` receives the full `useKernels()` return value as props (the hook instance lives in `AppContent` so the banner shares state): `interface SettingsPageProps { kernelLib: ReturnType<typeof useKernels> }`.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/SettingsPage.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import type { Kernel } from "../lib/api";

vi.mock("../lib/pickFolder", () => ({ pickFolder: vi.fn() }));

const kernel: Kernel = {
  id: "k1", version: "1.0.0.0", source: "imported",
  source_path: "D:\\kernels\\chromium-1.0.0.0", is_default: true,
  valid: true, profile_count: 2, created_at: "2026-01-01",
};

function makeLib(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    kernels: [kernel], loading: false, error: null,
    downloadState: { state: "idle" as const, error: null },
    refresh: vi.fn(), importKernel: vi.fn(), startDownload: vi.fn(),
    setDefault: vi.fn(), remove: vi.fn(),
    ...overrides,
  };
}

describe("SettingsPage", () => {
  it("renders kernel rows with version, source, path, default badge", () => {
    render(<SettingsPage kernelLib={makeLib()} />);
    expect(screen.getByText("1.0.0.0")).toBeInTheDocument();
    expect(screen.getByText(/D:\\kernels/)).toBeInTheDocument();
    expect(screen.getByText(/default/i)).toBeInTheDocument();
    expect(screen.getByText(/2 profile/i)).toBeInTheDocument();
  });

  it("flags invalid kernels", () => {
    const lib = makeLib({ kernels: [{ ...kernel, valid: false }] });
    render(<SettingsPage kernelLib={lib} />);
    expect(screen.getByText(/missing/i)).toBeInTheDocument();
  });

  it("import button picks a folder then calls importKernel", async () => {
    const { pickFolder } = await import("../lib/pickFolder");
    vi.mocked(pickFolder).mockResolvedValue("D:\\new-kernel");
    const lib = makeLib();
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /import/i }));
    await vi.waitFor(() => expect(lib.importKernel).toHaveBeenCalledWith("D:\\new-kernel"));
  });

  it("download button triggers startDownload", () => {
    const lib = makeLib();
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /download/i }));
    expect(lib.startDownload).toHaveBeenCalled();
  });

  it("shows progress while downloading", () => {
    const lib = makeLib({ downloadState: { state: "downloading", error: null } });
    render(<SettingsPage kernelLib={lib} />);
    expect(screen.getByText(/downloading/i)).toBeInTheDocument();
  });

  it("delete asks for confirmation", () => {
    const lib = makeLib();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SettingsPage kernelLib={lib} />);
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    expect(lib.remove).toHaveBeenCalledWith("k1");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/components/SettingsPage.test.tsx`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `SettingsPage.tsx`**

```tsx
import { Download, FolderOpen, Star, Trash2, TriangleAlert } from "lucide-react";
import type { useKernels } from "../hooks/useKernels";
import { pickFolder } from "../lib/pickFolder";

interface SettingsPageProps {
  kernelLib: ReturnType<typeof useKernels>;
}

export function SettingsPage({ kernelLib }: SettingsPageProps) {
  const { kernels, loading, error, downloadState, importKernel, startDownload, setDefault, remove } = kernelLib;

  const handleImport = async () => {
    const path = await pickFolder();
    if (path) await importKernel(path);
  };

  const handleDelete = (id: string, version: string) => {
    if (!confirm(`Remove kernel ${version} from the library?`)) return;
    void remove(id);
  };

  const downloading = downloadState.state === "downloading";

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h2 className="text-lg font-semibold mb-6">Settings</h2>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Browser Kernels
          </h3>
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleImport} className="btn-secondary flex items-center gap-1.5">
              <FolderOpen className="h-3.5 w-3.5" />
              <span>Import…</span>
            </button>
            <button
              type="button"
              onClick={() => void startDownload()}
              disabled={downloading}
              className="btn-primary flex items-center gap-1.5"
            >
              <Download className="h-3.5 w-3.5" />
              <span>{downloading ? "Downloading…" : "Download recommended"}</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="px-3 py-2 mb-3 rounded bg-red-600/15 border border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}
        {downloadState.state === "error" && downloadState.error && (
          <div className="px-3 py-2 mb-3 rounded bg-red-600/15 border border-red-600/30 text-red-400 text-sm">
            Download failed: {downloadState.error}
          </div>
        )}
        {downloading && (
          <div className="px-3 py-2 mb-3 rounded bg-surface-2 text-sm text-gray-300">
            Downloading browser kernel… this can take a few minutes.
          </div>
        )}

        {loading ? (
          <div className="text-gray-500 text-sm">Loading…</div>
        ) : kernels.length === 0 ? (
          <div className="text-gray-500 text-sm py-6 text-center border border-dashed border-border rounded">
            No kernels yet. Import a downloaded kernel directory or download the recommended version.
          </div>
        ) : (
          <ul className="space-y-2">
            {kernels.map((k) => (
              <li key={k.id} className="flex items-center gap-3 px-3 py-2 rounded bg-surface-1 border border-border">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium font-mono">{k.version}</span>
                    <span className="text-xs text-gray-500 capitalize">{k.source}</span>
                    {k.is_default && (
                      <span className="text-xs px-1.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">
                        default
                      </span>
                    )}
                    {!k.valid && (
                      <span className="inline-flex items-center gap-1 text-xs text-red-400">
                        <TriangleAlert className="h-3 w-3" /> missing on disk
                      </span>
                    )}
                  </div>
                  {k.source_path && (
                    <div className="text-xs text-gray-500 truncate">{k.source_path}</div>
                  )}
                  <div className="text-xs text-gray-500">
                    {k.profile_count} profile{k.profile_count === 1 ? "" : "s"}
                  </div>
                </div>
                {!k.is_default && k.valid && (
                  <button
                    type="button"
                    onClick={() => void setDefault(k.id)}
                    className="btn-secondary flex items-center gap-1 text-xs"
                    title="Set as default kernel"
                  >
                    <Star className="h-3 w-3" /> Set default
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleDelete(k.id, k.version)}
                  className="btn-danger flex items-center gap-1 text-xs"
                  aria-label={`Delete kernel ${k.version}`}
                >
                  <Trash2 className="h-3 w-3" /> Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Wire navigation + banner in `App.tsx`**

In `AppContent`:
- Add imports: `Settings` from `lucide-react`, `SettingsPage`, `useKernels`.
- Add state and hook:

```tsx
  const kernelLib = useKernels();
  const [page, setPage] = useState<"profiles" | "settings">("profiles");
```

- In the top bar's right-hand `div` (next to `LaunchButton`), add:

```tsx
            <button
              onClick={() => setPage(page === "settings" ? "profiles" : "settings")}
              className="text-gray-500 hover:text-gray-300 p-1"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>
```

- After the existing error banner, add the empty-library banner:

```tsx
        {!kernelLib.loading && kernelLib.kernels.length === 0 && page !== "settings" && (
          <div className="px-4 py-2 bg-amber-600/15 border-b border-amber-600/30 text-amber-400 text-sm flex items-center justify-between">
            <span>No browser kernel configured — profiles cannot launch yet.</span>
            <button className="underline" onClick={() => setPage("settings")}>
              Open Settings
            </button>
          </div>
        )}
```

- Wrap the content area: when `page === "settings"` render `<SettingsPage kernelLib={kernelLib} />` instead of the profile views (keep the sidebar visible; replace only the `{/* Content */}` div's children with a conditional).

- [ ] **Step 5: Run tests + build**

Run (in `frontend/`): `pnpm test && pnpm build`
Expected: PASS, type check clean

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): settings page with kernel library management and empty-state banner"
```

---

### Task 10: Kernel dropdown in the profile form

**Files:**
- Modify: `frontend/src/components/ProfileForm.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/components/ProfileForm.test.tsx` (append if exists; create otherwise)

**Interfaces:**
- Consumes: `Kernel` type (Task 6). `ProfileForm` gains a prop `kernels: Kernel[]`; `App.tsx` passes `kernelLib.kernels`.
- Produces: form submits `kernel_id: string | null` in `ProfileCreateData` (`null` = follow default).

- [ ] **Step 1: Write failing test**

In `frontend/src/components/ProfileForm.test.tsx` (create with minimal render helpers if absent — mock nothing, `ProfileForm` is pure):

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileForm } from "./ProfileForm";
import type { Kernel } from "../lib/api";

const kernels: Kernel[] = [
  { id: "k1", version: "1.0.0.0", source: "downloaded", source_path: null,
    is_default: true, valid: true, profile_count: 0, created_at: "2026-01-01" },
  { id: "k2", version: "2.0.0.0", source: "imported", source_path: "D:\\k2",
    is_default: false, valid: true, profile_count: 0, created_at: "2026-01-02" },
];

describe("ProfileForm kernel selection", () => {
  it("defaults to follow-default and lists kernels", () => {
    render(<ProfileForm profile={null} kernels={kernels} onSave={vi.fn()} onCancel={vi.fn()} />);
    const select = screen.getByLabelText(/kernel/i) as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByText(/follow default \(1\.0\.0\.0\)/i)).toBeInTheDocument();
    expect(screen.getByText("2.0.0.0")).toBeInTheDocument();
  });

  it("submits selected kernel_id", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} kernels={kernels} onSave={onSave} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/profile name/i), { target: { value: "P" } });
    fireEvent.change(screen.getByLabelText(/kernel/i), { target: { value: "k2" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));
    await vi.waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ kernel_id: "k2" })),
    );
  });
});
```

Note: `getByLabelText` requires the label to be associated — use `htmlFor`/`id` in the implementation below. The existing "Profile Name" label isn't associated; give the name input `id="profile-name"` and the label `htmlFor="profile-name"` as part of this task so the test works.

- [ ] **Step 2: Run test to verify it fails**

Run (in `frontend/`): `pnpm vitest run src/components/ProfileForm.test.tsx`
Expected: FAIL (no `kernels` prop / no kernel select)

- [ ] **Step 3: Implement**

`ProfileForm.tsx`:
- Props: add `kernels: Kernel[]` to `ProfileFormProps` (import `type Kernel` from `../lib/api`).
- Initial state: add `kernel_id: null,` to the `useState` initializer and `kernel_id: profile.kernel_id,` to the edit-mode `setForm` effect.
- In the **Basic** section grid, after the Fingerprint Seed field add:

```tsx
            <div className="col-span-2">
              <label className="label" htmlFor="profile-kernel">Browser Kernel</label>
              <select
                id="profile-kernel"
                className="input"
                value={form.kernel_id ?? ""}
                onChange={(e) => set("kernel_id", e.target.value || null)}
              >
                <option value="">
                  {(() => {
                    const def = kernels.find((k) => k.is_default);
                    return def ? `Follow default (${def.version})` : "Follow default (none configured)";
                  })()}
                </option>
                {kernels.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.version}{k.valid ? "" : " (missing on disk)"}
                  </option>
                ))}
              </select>
            </div>
```

- Associate the name label: `<label className="label" htmlFor="profile-name">Profile Name</label>` and `id="profile-name"` on its input.

`App.tsx`: pass `kernels={kernelLib.kernels}` to both `<ProfileForm ...>` usages.

- [ ] **Step 4: Run tests + build**

Run (in `frontend/`): `pnpm test && pnpm build`
Expected: PASS, type check clean

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): per-profile kernel selection in profile form"
```

---

### Task 11: Full verification + land

- [ ] **Step 1: Run everything**

```bash
backend/.venv/Scripts/python.exe -m pytest -q
cd frontend && pnpm test && pnpm build && cd ..
cargo test --manifest-path frontend/src-tauri/Cargo.toml
```

Expected: all PASS.

- [ ] **Step 2: Manual smoke (dev shell)**

Run `pnpm tauri dev` (in `frontend/`). Verify: app opens straight to main UI with the amber "No browser kernel configured" banner (assuming empty library); Settings → Import with a real kernel directory registers it and the banner disappears; a profile launches with it; deleting the kernel while the profile runs is refused. If no real kernel directory is available on the machine, verify import validation errors + the download button path instead.

- [ ] **Step 3: Update CLAUDE.md architecture notes**

In `CLAUDE.md`, update the **Launch flow** and **Lifecycle** paragraphs: kernel is no longer auto-downloaded; launch resolves the profile's kernel (or default) from the `kernels` table and pins `browser_version`; first-run shows a banner instead of a download screen. Keep it to a few sentences.

```bash
git add CLAUDE.md
git commit -m "docs: update architecture notes for kernel management"
```

- [ ] **Step 4: Land the plane**

Per CLAUDE.md session completion: file follow-up issues (bd if available, else markdown doc), `git pull --rebase`, `git push`, confirm `git status` is up to date.
