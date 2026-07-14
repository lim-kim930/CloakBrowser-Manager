# Tauri + Python Sidecar Desktop Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Docker+VNC web deployment with a cross-platform Tauri desktop app that launches the existing FastAPI backend as a PyInstaller sidecar, opening CloakBrowser windows natively on the user's desktop.

**Architecture:** A Tauri (Rust) shell packages the React frontend and spawns a frozen Python FastAPI server bound to `127.0.0.1:{port}`. The frontend talks to the backend over HTTP/CORS; Rust manages the sidecar lifecycle (spawn, health-poll, graceful shutdown). VNC virtual-display streaming is removed entirely — browsers are real desktop windows. Data moves from `/data` to OS app-data dirs. Automation still connects via the retained CDP reverse-proxy.

**Tech Stack:** Python ≥3.12 (FastAPI, uvicorn, cloakbrowser/Playwright, platformdirs, PyInstaller), React 19 + TypeScript + Vite + pnpm, Tauri v2 (Rust), `@tauri-apps/api`, `tauri-plugin-single-instance`.

## Global Constraints

- **Never bundle the CloakBrowser Chromium binary** into any distributed artifact (PyInstaller sidecar / Tauri installer). It downloads on first run via `cloakbrowser.download.ensure_binary()`. (`BINARY-LICENSE.md`)
- **Conventional Commits** (`feat:`, `fix:`, `chore:`, optional scope); one commit per logical task.
- **Backend is a package**: `backend/main.py` uses relative imports — always run as `python -m backend.main`, never `cd backend`.
- **Run tests from repo root**: `backend/.venv/Scripts/python.exe -m pytest -q` (pyproject sets `testpaths=backend/tests`, `asyncio_mode=auto`). The `conftest.py` cloakbrowser mock lets the suite run without the real binary.
- **Frontend from `frontend/`**: `pnpm test` = `vitest run` (jsdom); `pnpm build` = `tsc -b && vite build` (also the type check; no linter).
- **Default API port is 8000** (was 8080).
- **Target platform v1: Windows first**, architecture preserves cross-platform (platformdirs, target-triple naming, platform branches).
- Subagents writing/reviewing code must use the **Opus** model (user API gateway rejects non-Opus).

---

## File Structure

**Backend (`backend/`)**
- `main.py` — shrinks ~half: drop VNC proxy, clipboard, auth, static-serving; add `argparse` entry, `/api/health`, `/api/shutdown`, Origin/CORS middleware, stdin watchdog, programmatic uvicorn server.
- `browser_manager.py` — drop VNC/DISPLAY/swiftshader/viewport-hack/clipboard-injection; add kernel-readiness check and cache-dir env.
- `database.py` — `DATA_DIR` injected via `configure(data_dir)` instead of hardcoded `/data`.
- `models.py` — drop `vnc_ws_port`/`display`/`clipboard_sync`/`LoginRequest`/`ClipboardRequest`; add `HealthResponse`.
- `binary_status.py` *(new)* — thin wrapper tracking kernel download state (`downloading`/`ready`/`error`) for `/api/health`.
- `build.py` *(new)* — PyInstaller driver producing the sidecar with target-triple naming.
- Deleted: `vnc_manager.py`, `tests/test_vnc_manager.py`, `tests/test_rfb.py`, `tests/test_auth.py`.

**Frontend (`frontend/src/`)**
- `bootstrap/useBootstrap.ts` *(new)* — Tauri startup state machine.
- `bootstrap/tauri.ts` *(new)* — `isTauri()`, event/invoke wrappers.
- `bootstrap/PortConfigModal.tsx`, `bootstrap/DownloadingScreen.tsx`, `bootstrap/BackendErrorScreen.tsx` *(new)*.
- `lib/api.ts` — add `setApiBase()`; drop auth + clipboard; add `health()`.
- `App.tsx` — add bootstrap gate; delete auth branches and VNC `view` state.
- `components/CdpCopyButton.tsx` *(new)* — copy CDP URL in `ProfileForm`.
- Deleted: `components/ProfileViewer.tsx`, `components/LoginPage.tsx`, `novnc.d.ts`.

**Tauri (`frontend/src-tauri/`)** *(all new)*
- `tauri.conf.json`, `Cargo.toml`, `build.rs`, `capabilities/default.json`, `src/main.rs`, `src/lib.rs` (all supervision logic lives in `lib.rs`, ~300 lines).

**Root**
- Deleted: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `implementation_plan.md`.
- Modified: `.gitignore`, `README.md`, `CLAUDE.md`.

---

## Milestone 1 — Backend decoupling

Removes VNC/auth/clipboard/static-serving; adds the argparse entry, health, shutdown, Origin/CORS middleware, database path injection, and model convergence. Tests green at the end.

### Task 1: Database path injection

**Files:**
- Modify: `backend/database.py:14-15`
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Produces: `db.configure(data_dir: Path) -> None` — sets module globals `DATA_DIR` and `DB_PATH`. `DATA_DIR` default stays `Path("/data")` until configured.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_database.py`:

```python
def test_configure_sets_data_dir_and_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # configure() mutates module globals — snapshot current values so
    # monkeypatch restores them after the test (no cross-test pollution).
    monkeypatch.setattr(db, "DATA_DIR", db.DATA_DIR)
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)

    db.configure(tmp_path / "appdata")
    assert db.DATA_DIR == tmp_path / "appdata"
    assert db.DB_PATH == tmp_path / "appdata" / "profiles.db"
    # user_data_dir for new profiles derives from the configured DATA_DIR
    db.init_db()
    p = db.create_profile("Cfg")
    assert p["user_data_dir"].startswith(str(tmp_path / "appdata"))
```

(`import pytest` at the top of the file if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_database.py::test_configure_sets_data_dir_and_db_path -q`
Expected: FAIL with `AttributeError: module 'backend.database' has no attribute 'configure'`

- [ ] **Step 3: Write minimal implementation**

Replace `backend/database.py:14-15`:

```python
DATA_DIR = Path("/data")  # default; overridden by configure() at startup
DB_PATH = DATA_DIR / "profiles.db"


def configure(data_dir: Path | str) -> None:
    """Point the database at a data directory. Call before init_db()."""
    global DATA_DIR, DB_PATH
    DATA_DIR = Path(data_dir)
    DB_PATH = DATA_DIR / "profiles.db"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_database.py -q`
Expected: PASS (all database tests)

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_database.py
git commit -m "feat(backend): inject data dir via database.configure()"
```

---

### Task 2: Model convergence (drop VNC/auth/clipboard, add HealthResponse)

**Files:**
- Modify: `backend/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces:
  - `BinaryStatus(state: Literal["downloading","ready","error"], version: str|None, error: str|None)`
  - `HealthResponse(status: str = "ok", version: str, binary: BinaryStatus)`
  - `LaunchResponse(profile_id: str, status: str = "running", cdp_url: str|None = None)` — **no** `vnc_ws_port`/`display`.
  - `ProfileStatusResponse(status: str, cdp_url: str|None = None)` — **no** `vnc_ws_port`/`display`.
  - `ProfileResponse` — **no** `vnc_ws_port`, **no** `clipboard_sync`.
  - `ProfileCreate`/`ProfileUpdate` — **no** `clipboard_sync`.
- Still present (deleted later): `LoginRequest` (Task 4), `ClipboardRequest` (Task 5) — `main.py` imports them until its own surgery tasks.

- [ ] **Step 1: Rewrite the model tests**

Replace the `ClipboardRequest`, `LaunchResponse`, `ProfileStatusResponse` test sections in `backend/tests/test_models.py`. Remove the `ClipboardRequest` import and its 3 tests. Replace the `LaunchResponse` and `ProfileStatusResponse` blocks with:

```python
# ── LaunchResponse ──────────────────────────────────────────────────────────


def test_launch_response_with_cdp_url():
    r = LaunchResponse(profile_id="abc", cdp_url="/api/profiles/abc/cdp")
    assert r.cdp_url == "/api/profiles/abc/cdp"
    assert r.status == "running"


def test_launch_response_cdp_url_default_none():
    r = LaunchResponse(profile_id="abc")
    assert r.cdp_url is None


# ── ProfileStatusResponse ──────────────────────────────────────────────────


def test_profile_status_response_running():
    r = ProfileStatusResponse(status="running", cdp_url="/api/profiles/abc/cdp")
    assert r.cdp_url == "/api/profiles/abc/cdp"


def test_profile_status_response_stopped():
    r = ProfileStatusResponse(status="stopped")
    assert r.cdp_url is None


# ── HealthResponse ──────────────────────────────────────────────────────────


def test_health_response_ready():
    from backend.models import BinaryStatus, HealthResponse

    h = HealthResponse(version="0.1.0", binary=BinaryStatus(state="ready", version="0.4.10"))
    assert h.status == "ok"
    assert h.binary.state == "ready"
    assert h.binary.error is None


def test_health_response_error_state():
    from backend.models import BinaryStatus, HealthResponse

    h = HealthResponse(version="0.1.0", binary=BinaryStatus(state="error", error="boom"))
    assert h.binary.error == "boom"
```

Update the top-of-file import to drop `ClipboardRequest`:

```python
from backend.models import (
    LaunchResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileStatusResponse,
    ProfileUpdate,
    StatusResponse,
    TagCreate,
    TagResponse,
)
```

Also update `test_profile_create_all_fields` — remove any `clipboard_sync` usage (it isn't currently passed there, so no change needed) and delete `test_profile_clipboard_*` if present (none in test_models.py).

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -q`
Expected: FAIL — `ImportError` (ClipboardRequest gone from imports but still referenced) or `HealthResponse` not found.

- [ ] **Step 3: Rewrite models.py**

Apply these edits to `backend/models.py`:

Remove `clipboard_sync: bool = True` from `ProfileCreate` (line 27) and `clipboard_sync: bool | None = None` from `ProfileUpdate` (line 52).

In `ProfileResponse`, remove `clipboard_sync: bool = True` (line 88), remove the `coerce_clipboard_sync` validator (lines 91-94), and remove `vnc_ws_port: int | None = None` (line 104).

Replace `LaunchResponse` (lines 108-113):

```python
class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    cdp_url: str | None = None
```

Replace `ProfileStatusResponse` (lines 122-126):

```python
class ProfileStatusResponse(BaseModel):
    status: str  # "running" | "stopped"
    cdp_url: str | None = None
```

**Keep `ClipboardRequest` and `LoginRequest` untouched in this task.** `main.py` still imports both; deleting them here would break every test that imports `backend.main`. `LoginRequest` is deleted in Task 4 (auth removal), `ClipboardRequest` in Task 5 (clipboard removal). Only their tests are removed in this task. Append the health models:

```python
class BinaryStatus(BaseModel):
    state: Literal["downloading", "ready", "error"]
    version: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    binary: BinaryStatus
```

- [ ] **Step 4: Remove the clipboard_sync API tests**

`backend/tests/test_api.py` asserts `clipboard_sync` in profile responses; the field is gone from `ProfileResponse` now. Delete these two tests (lines 233-248) and the `# ── Clipboard Sync Setting ──` section header above them:

- `test_profile_clipboard_sync_default_true`
- `test_profile_clipboard_sync_update`

(The clipboard *endpoint* tests — `test_set_clipboard_*`, `test_get_clipboard_*` — stay until Task 5.)

- [ ] **Step 5: Run the full suite to verify green**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — `main.py` passing now-unknown fields like `vnc_ws_port=` into these models is harmless (pydantic v2 defaults to `extra="ignore"`), so the API keeps working mid-migration.

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/tests/test_models.py
git commit -m "feat(backend): converge models — drop VNC/auth/clipboard, add HealthResponse"
```

---

### Task 3: Binary status tracker

**Files:**
- Create: `backend/binary_status.py`
- Test: `backend/tests/test_binary_status.py`

**Interfaces:**
- Produces:
  - `BinaryStatusTracker` with `.snapshot() -> dict` (keys `state`, `version`, `error`), `.mark_downloading()`, `.mark_ready(version: str|None)`, `.mark_error(error: str)`. Initial state `"downloading"`.
  - `run_ensure_binary(tracker, ensure_fn, version_fn) -> None` — calls `ensure_fn()`, then `version_fn()`, updating the tracker; catches exceptions into `mark_error`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_binary_status.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_status.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.binary_status'`

- [ ] **Step 3: Write the implementation**

Create `backend/binary_status.py`:

```python
"""Track CloakBrowser Chromium kernel download/readiness state for /api/health.

The kernel is downloaded on first run by cloakbrowser.ensure_binary() (blocking).
This tracker is updated from a background thread so the health endpoint can report
downloading / ready / error without blocking startup.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Literal

logger = logging.getLogger("cloakbrowser.manager.binary")

State = Literal["downloading", "ready", "error"]


class BinaryStatusTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: State = "downloading"
        self._version: str | None = None
        self._error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "version": self._version, "error": self._error}

    def mark_downloading(self) -> None:
        with self._lock:
            self._state = "downloading"
            self._error = None

    def mark_ready(self, version: str | None) -> None:
        with self._lock:
            self._state = "ready"
            self._version = version
            self._error = None

    def mark_error(self, error: str) -> None:
        with self._lock:
            self._state = "error"
            self._error = error


def run_ensure_binary(
    tracker: BinaryStatusTracker,
    ensure_fn: Callable[[], object],
    version_fn: Callable[[], str | None],
) -> None:
    """Ensure the kernel is present, updating the tracker. Blocking — run in a thread."""
    tracker.mark_downloading()
    try:
        ensure_fn()
    except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
        logger.error("Kernel ensure_binary failed: %s", exc)
        tracker.mark_error(str(exc))
        return
    try:
        version = version_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kernel version lookup failed: %s", exc)
        version = None
    tracker.mark_ready(version)
    logger.info("Kernel ready (version=%s)", version)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_status.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/binary_status.py backend/tests/test_binary_status.py
git commit -m "feat(backend): add kernel readiness tracker for /api/health"
```

---

### Task 4: Remove auth (middleware, endpoints, LoginRequest)

The desktop backend binds `127.0.0.1` only; token auth and the login page go away (Origin protection arrives in Task 9).

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/models.py` (delete `LoginRequest`)
- Modify: `backend/tests/test_api.py` (delete the wss test)
- Delete: `backend/tests/test_auth.py`

- [ ] **Step 1: Delete the auth test file and the wss test**

```bash
git rm backend/tests/test_auth.py
```

In `backend/tests/test_api.py`, delete `test_cdp_json_version_uses_wss_behind_https` (lines 419-442) — HTTPS reverse-proxying is gone with the web deployment; CDP URLs are always `ws://` now.

- [ ] **Step 2: Excise auth from main.py**

Delete from `backend/main.py`:
- Imports that only auth used: `hmac`, `from http.cookies import SimpleCookie`, `import starlette.requests`, `Response` from the fastapi import line, `JSONResponse` from the responses import line (re-added in Task 9), and `LoginRequest` from the models import.
- `AUTH_TOKEN` and `_AUTH_EXEMPT` constants (lines 48-54).
- `_check_auth` (lines 57-80), `_is_https` (lines 83-86), the whole `AuthMiddleware` class (lines 139-173).
- `app.add_middleware(AuthMiddleware)` (line 390).
- The `# ── Authentication ──` section: `auth_status`, `auth_login`, `auth_logout` endpoints (lines 393-432).

`_is_https` had two remaining callers in the CDP rewrites. In `cdp_json_version`, replace:

```python
    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    data["webSocketDebuggerUrl"] = f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp"
```

with:

```python
    host = request.headers.get("host", "127.0.0.1:8000")
    data["webSocketDebuggerUrl"] = f"ws://{host}/api/profiles/{profile_id}/cdp"
```

In `cdp_json_list`, replace:

```python
    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    for entry in data:
        if "webSocketDebuggerUrl" in entry:
            ws_path = entry["webSocketDebuggerUrl"].split("/devtools/")[-1]
            entry["webSocketDebuggerUrl"] = (
                f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp/devtools/{ws_path}"
            )
```

with:

```python
    host = request.headers.get("host", "127.0.0.1:8000")
    for entry in data:
        if "webSocketDebuggerUrl" in entry:
            ws_path = entry["webSocketDebuggerUrl"].split("/devtools/")[-1]
            entry["webSocketDebuggerUrl"] = (
                f"ws://{host}/api/profiles/{profile_id}/cdp/devtools/{ws_path}"
            )
```

In `backend/models.py`, delete the `LoginRequest` class.

- [ ] **Step 3: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. `test_cdp_json_version_rewrites_ws_url` still passes — it asserts `ws://testserver/...` which the hardcoded scheme still produces.

- [ ] **Step 4: Commit**

```bash
git add -A backend
git commit -m "refactor(backend)!: remove AUTH_TOKEN auth — desktop binds localhost only"
```

---

### Task 5: Remove VNC proxy, RFB filtering, clipboard relay, and static serving

`main.py` shrinks by ~600 lines. The CDP proxy stays intact.

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/models.py` (delete `ClipboardRequest`)
- Modify: `backend/tests/test_api.py`
- Delete: `backend/tests/test_rfb.py`

- [ ] **Step 1: Delete test files and test cases**

```bash
git rm backend/tests/test_rfb.py
```

In `backend/tests/test_api.py` delete:
- The `# ── Clipboard ──` section: `test_set_clipboard_not_running`, `test_get_clipboard_not_running`, `test_set_clipboard_success`, `test_get_clipboard_from_page` (lines 251-315).
- The `# ── WebSocket Origin Validation ──` section: `test_vnc_ws_rejects_cross_origin`, `test_cdp_ws_rejects_cross_origin`, `test_ws_allows_same_origin`, `test_ws_allows_no_origin` (lines 497-563). Origin enforcement moves to middleware in Task 9, which brings its own tests.
- Now-unused imports at the top if any (`dataclass` is already unused; remove it).

- [ ] **Step 2: Excise VNC/clipboard/static from main.py**

Delete from `backend/main.py`:
- Module docstring — replace with:

```python
"""CloakBrowser Manager — FastAPI backend.

REST API + CDP reverse proxy for the CloakBrowser desktop client.
Runs as a Tauri sidecar (PyInstaller-frozen) or from source for development.
Browsers launch as real windows on the user's desktop; there is no VNC layer.
"""
```

- Imports that only VNC/clipboard/static used: `struct`, `from urllib.parse import urlparse`, `FileResponse` and `StaticFiles` imports, `ClipboardRequest` from the models import.
- `FRONTEND_DIR` constant.
- `_check_websocket_origin` (the whole function) **and its calls** at the top of `cdp_proxy` and `cdp_page_proxy` (`if not await _check_websocket_origin(websocket): return`). Its same-host rule would block the Tauri WebView (origin `http://tauri.localhost` ≠ host `127.0.0.1:8000`); the whitelist middleware in Task 9 replaces it.
- The entire RFB translator/filter section (lines 183-372): `_parse_kasmvnc_clipboard`, `_build_server_cut_text`, `_RFB_MSG_SIZE`, `_RFB_EXTENSION_SIZE`, `_ALLOWED_ENCODINGS`, `_rfb_msg_length`, `_rewrite_set_encodings`, `_rewrite_pointer_event`, `_filter_rfb_client_messages`.
- The `# ── Clipboard Relay ──` section: `_CLIPBOARD_MAX_READ`, `_xclip_procs`, `set_clipboard`, `get_clipboard`.
- The `# ── VNC WebSocket Proxy ──` section: the whole `vnc_proxy` endpoint.
- The `# ── Static Frontend ──` section: the `if FRONTEND_DIR.exists():` block with the `/assets` mount and `serve_spa`.

Keep: `shutil` and `Path` imports (used by `delete_profile`), `WebSocketDisconnect` (used by `_proxy_cdp_websocket`), the whole CDP section.

- [ ] **Step 3: Stop returning VNC fields from endpoints**

In `list_profiles`, `create_profile`, `get_profile`, `update_profile`, delete the line:

```python
    p["vnc_ws_port"] = status["vnc_ws_port"]
```

(in `create_profile`/`get_profile`/`update_profile` the variable is `profile` instead of `p`). Replace the `launch_profile` return statement:

```python
    return LaunchResponse(
        profile_id=profile_id,
        status="running",
        cdp_url=f"/api/profiles/{profile_id}/cdp",
    )
```

In `backend/models.py`, delete the `ClipboardRequest` class.

- [ ] **Step 4: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. `browser_manager`/`vnc_manager` are untouched so far — `get_status()` still returns `vnc_ws_port`/`display` keys, which the slimmed models now ignore.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "refactor(backend)!: remove VNC/RFB proxy, clipboard relay, and static serving"
```

---

### Task 6: Desktop-native browser_manager (drop VNC manager, DISPLAY, viewport hack)

**Files:**
- Modify: `backend/browser_manager.py`
- Modify: `backend/main.py` (lifespan)
- Modify: `backend/tests/conftest.py`, `backend/tests/test_browser_manager.py`, `backend/tests/test_api.py`
- Delete: `backend/vnc_manager.py`, `backend/tests/test_vnc_manager.py`

**Interfaces:**
- Produces: `RunningProfile(profile_id: str, context: Any, cdp_port: int)` — `display`/`ws_port` fields are gone.
- Produces: `BrowserManager.get_status(profile_id) -> {"status": "running"|"stopped", "cdp_url": str|None}`.
- Removed: `BrowserManager.cleanup_stale()` (it only killed orphan Xvnc; Playwright's driver kills orphan Chromium itself).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_browser_manager.py` (needs `from unittest.mock import AsyncMock, MagicMock` at the top):

```python
# ── Desktop launch behavior ──────────────────────────────────────────────────


async def test_launch_headed_no_viewport_no_env(tmp_path, monkeypatch):
    """Headed desktop launch must not pass viewport or env (cloakbrowser
    defaults to no_viewport; DISPLAY injection was VNC-only)."""
    from backend import browser_manager as bm

    mock_launch = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", mock_launch)

    mgr = BrowserManager()
    profile = {
        "id": "p1",
        "name": "Desktop",
        "user_data_dir": str(tmp_path / "p1"),
        "fingerprint_seed": 7,
    }
    running = await mgr.launch(profile)

    kwargs = mock_launch.call_args.kwargs
    assert "viewport" not in kwargs
    assert "env" not in kwargs
    assert any(a.startswith("--remote-debugging-port=") for a in kwargs["args"])
    assert running.cdp_port == BASE_CDP_PORT
    assert mgr.get_status("p1") == {"status": "running", "cdp_url": "/api/profiles/p1/cdp"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_browser_manager.py::test_launch_headed_no_viewport_no_env -q`
Expected: FAIL — current `launch()` calls `self.vnc.allocate()` which spawns nothing in tests but the mocked context lacks `display`, and `viewport`/`env` ARE in kwargs.

- [ ] **Step 3: Rewrite browser_manager.py**

```bash
git rm backend/vnc_manager.py backend/tests/test_vnc_manager.py
```

In `backend/browser_manager.py`:
- Delete `import os` (only used for the `env` kwarg) and `from .vnc_manager import VNCManager`.
- `RunningProfile` becomes:

```python
@dataclass
class RunningProfile:
    profile_id: str
    context: Any  # Playwright BrowserContext
    cdp_port: int
```

- In `__init__`, delete `self.vnc = VNCManager()`.
- Replace the whole `launch()` method:

```python
    async def launch(self, profile: dict[str, Any]) -> RunningProfile:
        """Launch a browser instance for the given profile."""
        profile_id = profile["id"]

        async with self._lock:
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            self._launching.add(profile_id)

        try:
            cdp_port = self._allocate_cdp_port()

            # Clean stale Chromium lock files (left by previous crashes)
            user_data_dir = Path(profile["user_data_dir"])
            for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                (user_data_dir / lock_file).unlink(missing_ok=True)

            # Set up bookmarks and search engine on first launch
            _init_profile_defaults(user_data_dir)

            # Build fingerprint args from profile settings
            extra_args = self._build_fingerprint_args(profile)
            extra_args += profile.get("launch_args") or []
            extra_args.append(f"--remote-debugging-port={cdp_port}")

            # Normalize proxy format (host:port:user:pass → http://user:pass@host:port)
            raw_proxy = profile.get("proxy") or None
            proxy = _normalize_proxy(raw_proxy) if raw_proxy else None
            if proxy:
                _validate_proxy(proxy)

            # Headed desktop launch: no viewport override — cloakbrowser defaults
            # to no_viewport so outerWidth >= innerWidth stays consistent.
            context = await launch_persistent_context_async(
                user_data_dir=profile["user_data_dir"],
                headless=bool(profile.get("headless", False)),
                proxy=proxy,
                args=extra_args,
                timezone=profile.get("timezone") or None,
                locale=profile.get("locale") or None,
                humanize=bool(profile.get("humanize", False)),
                human_preset=profile.get("human_preset", "default"),
                geoip=bool(profile.get("geoip", False)),
                color_scheme=profile.get("color_scheme") or None,
                user_agent=profile.get("user_agent") or None,
            )

            running = RunningProfile(
                profile_id=profile_id, context=context, cdp_port=cdp_port,
            )

            # Auto-cleanup if the browser crashes or the user closes the window
            context.on("close", lambda: asyncio.ensure_future(
                self._on_browser_closed(profile_id)
            ))

            async with self._lock:
                self.running[profile_id] = running
                self._launching.discard(profile_id)

            logger.info("Launched profile %s (cdp_port=%d)", profile_id, cdp_port)
            return running

        except BaseException:
            async with self._lock:
                self._launching.discard(profile_id)
            raise
```

- Replace `_on_browser_closed`, `stop`, `get_status`, `cleanup_all`; delete `cleanup_stale`:

```python
    async def _on_browser_closed(self, profile_id: str):
        """Called when the browser exits (crash, user closed the window, or stop())."""
        async with self._lock:
            running = self.running.pop(profile_id, None)
        if running:
            logger.info("Browser closed for profile %s", profile_id)

    async def stop(self, profile_id: str):
        """Stop a running browser instance (graceful — session data is flushed)."""
        # Pop before close so _on_browser_closed() finds nothing to clean up
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if not running:
            return

        logger.info("Stopping profile %s", profile_id)
        try:
            await running.context.close()
        except Exception as exc:
            logger.warning("Error closing context for %s: %s", profile_id, exc)

    def get_status(self, profile_id: str) -> dict[str, Any]:
        """Get running status for a profile."""
        if profile_id in self.running:
            return {"status": "running", "cdp_url": f"/api/profiles/{profile_id}/cdp"}
        return {"status": "stopped", "cdp_url": None}

    async def cleanup_all(self):
        """Stop all running profiles. Called on shutdown."""
        async with self._lock:
            profile_ids = list(self.running.keys())
        for pid in profile_ids:
            await self.stop(pid)
```

- In `_build_fingerprint_args`, delete the line `"--use-angle=swiftshader",  # software GL for VNC (no GPU in container)`.
- Delete the clipboard init-script block (`_clipboard_init_js` and its injection loop) — it lived inside the old `launch()`, so the rewrite above already drops it.

- [ ] **Step 4: Adapt callers and fixtures**

`backend/main.py` — in `lifespan`, delete the line `await browser_mgr.cleanup_stale()`.

`backend/tests/conftest.py` — in `app_client`, delete:

```python
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
```

(keep the `cleanup_all` mock line).

`backend/tests/test_browser_manager.py`:
- `test_build_args_always_includes_base`: delete the `assert "--use-angle=swiftshader" in args` line.
- `test_build_args_empty_profile`: change to `assert len(args) == 2  # --disable-infobars, --test-type`.

`backend/tests/test_api.py` — `MagicMock(spec=RunningProfile)` now rejects `display`/`ws_port`. In `_mock_running_profile` and the inline mocks in `test_delete_profile_stops_running` and `test_launch_already_running`, keep only `cdp_port` and `profile_id`:

```python
def _mock_running_profile(pid: str) -> MagicMock:
    """Create a mock RunningProfile and register it in browser_mgr."""
    mock = MagicMock(spec=RunningProfile)
    mock.cdp_port = 5100
    mock.profile_id = pid
    main.browser_mgr.running[pid] = mock
    return mock
```

In `test_launch_failure_500`, change the side effect to `RuntimeError("driver crashed")` (Xvnc no longer exists).

- [ ] **Step 5: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "refactor(backend)!: desktop-native launches — drop VNC manager, DISPLAY, viewport hack"
```

---

### Task 7: Kernel readiness gating (launch 503, auto-launch waits)

**Files:**
- Modify: `backend/binary_status.py`, `backend/browser_manager.py`, `backend/main.py`
- Modify: `backend/tests/conftest.py`, `backend/tests/test_browser_manager.py`, `backend/tests/test_api.py`, `backend/tests/test_binary_status.py`

**Interfaces:**
- Produces: `binary_status.tracker` — module-level `BinaryStatusTracker` singleton.
- Produces: `binary_status.start_background_ensure() -> threading.Thread` — runs `ensure_binary()` in a daemon thread against the singleton.
- Produces: `browser_manager.BinaryNotReadyError(RuntimeError)` — raised by `launch()` when the kernel isn't ready; `main.py` maps it to HTTP 503.

- [ ] **Step 1: Mock cloakbrowser.download in conftest and add a readiness fixture**

In `backend/tests/conftest.py`, extend the mock block (after the `_mock_config` lines):

```python
_mock_download = types.ModuleType("cloakbrowser.download")
_mock_download.ensure_binary = MagicMock()  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)
sys.modules.setdefault("cloakbrowser.download", _mock_download)
_mock_cloakbrowser.config = _mock_config  # type: ignore[attr-defined]
_mock_cloakbrowser.download = _mock_download  # type: ignore[attr-defined]
```

(`MagicMock` is already imported.) Update the backend import line and add fixtures:

```python
from backend import binary_status, database as db  # noqa: E402


@pytest.fixture()
def kernel_ready():
    """Force the kernel tracker to ready; restore to downloading afterwards."""
    binary_status.tracker.mark_ready("0.0.0-test")
    yield
    binary_status.tracker.mark_downloading()
```

Change `app_client` to depend on it and to skip the real background thread:

```python
@pytest.fixture()
def app_client(tmp_db: Path, kernel_ready, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB, ready kernel, and no real cleanup."""
    from backend import main

    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(binary_status, "start_background_ensure", lambda: None)

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_binary_status.py`:

```python
def test_module_tracker_singleton_exists():
    from backend import binary_status

    assert isinstance(binary_status.tracker, BinaryStatusTracker)


def test_start_background_ensure_marks_ready():
    import sys

    from backend import binary_status

    thread = binary_status.start_background_ensure()
    thread.join(timeout=5)
    snap = binary_status.tracker.snapshot()
    assert snap["state"] == "ready"
    assert snap["version"] == "0.0.0-test"  # from the conftest cloakbrowser mock
    sys.modules["cloakbrowser.download"].ensure_binary.assert_called()
    binary_status.tracker.mark_downloading()  # restore for other tests
```

Append to `backend/tests/test_browser_manager.py`:

```python
async def test_launch_raises_when_kernel_not_ready(tmp_path):
    from backend import binary_status
    from backend.browser_manager import BinaryNotReadyError

    binary_status.tracker.mark_downloading()
    mgr = BrowserManager()
    with pytest.raises(BinaryNotReadyError):
        await mgr.launch({"id": "x", "user_data_dir": str(tmp_path)})
    assert "x" not in mgr._launching  # launch slot released


async def test_auto_launch_waits_for_kernel(tmp_db, monkeypatch):
    import asyncio

    from backend import binary_status, database as db

    db.create_profile(name="Auto", auto_launch=True)
    mgr = BrowserManager()
    launched: list[str] = []

    async def fake_launch(profile):
        launched.append(profile["id"])

    monkeypatch.setattr(mgr, "launch", fake_launch)
    binary_status.tracker.mark_downloading()
    task = asyncio.create_task(mgr.auto_launch_all())
    await asyncio.sleep(0.05)
    assert launched == []  # still waiting for the kernel
    binary_status.tracker.mark_ready("0.0.0-test")
    await asyncio.wait_for(task, timeout=5)
    assert len(launched) == 1
    binary_status.tracker.mark_downloading()


async def test_auto_launch_aborts_on_kernel_error(tmp_db, monkeypatch):
    import asyncio

    from backend import binary_status, database as db

    db.create_profile(name="Auto2", auto_launch=True)
    mgr = BrowserManager()
    launched: list[str] = []

    async def fake_launch(profile):
        launched.append(profile["id"])

    monkeypatch.setattr(mgr, "launch", fake_launch)
    binary_status.tracker.mark_error("no network")
    await asyncio.wait_for(mgr.auto_launch_all(), timeout=5)
    assert launched == []
    binary_status.tracker.mark_downloading()
```

Update `test_launch_headed_no_viewport_no_env` (from Task 6) — the gate would now reject it. Add the fixture and readiness setup at the top:

```python
async def test_launch_headed_no_viewport_no_env(tmp_path, monkeypatch, kernel_ready):
```

(body unchanged — `kernel_ready` comes from conftest).

Append to `backend/tests/test_api.py` in the Launch section:

```python
def test_launch_kernel_not_ready_503(app_client: TestClient):
    """BinaryNotReadyError from launch maps to 503."""
    from backend.browser_manager import BinaryNotReadyError

    create = app_client.post("/api/profiles", json={"name": "NotReady"})
    pid = create.json()["id"]
    main.browser_mgr.launch = AsyncMock(side_effect=BinaryNotReadyError("Browser core not ready"))
    resp = app_client.post(f"/api/profiles/{pid}/launch")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Browser core not ready"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_status.py backend/tests/test_browser_manager.py -q`
Expected: FAIL — `tracker`/`start_background_ensure`/`BinaryNotReadyError` don't exist yet.

- [ ] **Step 4: Implement**

Append to `backend/binary_status.py`:

```python
# Module-level singleton — shared by main.py (health endpoint, lifespan)
# and browser_manager (launch gating).
tracker = BinaryStatusTracker()


def _ensure_kernel() -> None:
    from cloakbrowser.download import ensure_binary

    ensure_binary()


def _kernel_version() -> str | None:
    from cloakbrowser.config import CHROMIUM_VERSION

    return CHROMIUM_VERSION


def start_background_ensure() -> threading.Thread:
    """Kick off the (blocking) kernel download in a daemon thread."""
    thread = threading.Thread(
        target=run_ensure_binary,
        args=(tracker, _ensure_kernel, _kernel_version),
        name="ensure-binary",
        daemon=True,
    )
    thread.start()
    return thread
```

In `backend/browser_manager.py`:
- Add `from . import binary_status` below the cloakbrowser import.
- Add the exception class above `BASE_CDP_PORT`:

```python
class BinaryNotReadyError(RuntimeError):
    """Launch attempted before the Chromium kernel finished downloading."""
```

- In `launch()`, insert as the very first statement (before the lock):

```python
        if binary_status.tracker.snapshot()["state"] != "ready":
            raise BinaryNotReadyError("Browser core not ready")
```

- In `auto_launch_all()`, insert a wait loop after the `if not auto_profiles: return` block, before the "Auto-launching" log line (the 1s poll is fine for the tests — they assert "nothing launched yet" after 0.05s and wrap completion in `asyncio.wait_for(..., timeout=5)`):

```python
        # Wait for the kernel — on first run it may still be downloading.
        while True:
            state = binary_status.tracker.snapshot()["state"]
            if state == "ready":
                break
            if state == "error":
                logger.error("Auto-launch aborted: browser core failed to download")
                return
            await asyncio.sleep(1)
```

In `backend/main.py`:
- Import: `from . import binary_status` and change the browser_manager import to `from .browser_manager import BinaryNotReadyError, BrowserManager`.
- In `lifespan`, after `db.init_db()`: `binary_status.start_background_ensure()`.
- In `launch_profile`, add the 503 mapping as the first `except` clause:

```python
    try:
        await browser_mgr.launch(profile)
    except BinaryNotReadyError:
        raise HTTPException(status_code=503, detail="Browser core not ready")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to launch profile %s: %s", profile_id, exc)
        raise HTTPException(status_code=500, detail="Failed to launch browser")
```

(the returned `running` variable is no longer used by the response — bind it or drop it; use `await browser_mgr.launch(profile)` bare.)

- [ ] **Step 5: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(backend): gate launches on kernel readiness, auto-launch waits for download"
```

---

### Task 8: /api/health and /api/shutdown endpoints

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `GET /api/health` → `{"status": "ok", "version": "<manager>", "binary": {"state": "downloading|ready|error", "version": str|null, "error": str|null}}` (the contract the Rust shell and frontend poll).
- Produces: `POST /api/shutdown` → `{"ok": true}`; sets `uvicorn.Server.should_exit`.
- Produces: `main.request_shutdown()` and module global `main._uvicorn_server` (set by the Task 10 entry point; the stdin watchdog calls `request_shutdown` too).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
# ── Health ──────────────────────────────────────────────────────────────────


def test_health_ready(app_client: TestClient):
    from backend import binary_status

    binary_status.tracker.mark_ready("135.0.1")
    resp = app_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == main.MANAGER_VERSION
    assert data["binary"] == {"state": "ready", "version": "135.0.1", "error": None}


def test_health_downloading(app_client: TestClient):
    from backend import binary_status

    binary_status.tracker.mark_downloading()
    resp = app_client.get("/api/health")
    assert resp.json()["binary"]["state"] == "downloading"
    binary_status.tracker.mark_ready("0.0.0-test")  # restore for app_client teardown


def test_health_error(app_client: TestClient):
    from backend import binary_status

    binary_status.tracker.mark_error("disk full")
    resp = app_client.get("/api/health")
    data = resp.json()
    assert data["binary"]["state"] == "error"
    assert data["binary"]["error"] == "disk full"
    binary_status.tracker.mark_ready("0.0.0-test")


# ── Shutdown ────────────────────────────────────────────────────────────────


def test_shutdown_sets_should_exit(app_client: TestClient, monkeypatch):
    from types import SimpleNamespace

    fake_server = SimpleNamespace(should_exit=False)
    monkeypatch.setattr(main, "_uvicorn_server", fake_server)
    resp = app_client.post("/api/shutdown")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert fake_server.should_exit is True


def test_shutdown_without_server_still_ok(app_client: TestClient, monkeypatch):
    """Dev mode (uvicorn CLI): no server ref — endpoint must not crash."""
    monkeypatch.setattr(main, "_uvicorn_server", None)
    resp = app_client.post("/api/shutdown")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k "health or shutdown" -q`
Expected: FAIL with 404s (endpoints don't exist).

- [ ] **Step 3: Implement**

In `backend/main.py`:
- Add `import uvicorn` to the third-party imports; add `BinaryStatus` and `HealthResponse` to the models import.
- Below the `browser_mgr = BrowserManager()` line:

```python
MANAGER_VERSION = "0.1.0"

# Set by main() so /api/shutdown and the stdin watchdog can stop the server.
_uvicorn_server: uvicorn.Server | None = None


def request_shutdown() -> None:
    """Ask the running uvicorn server to exit gracefully (lifespan cleanup runs)."""
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
    else:
        logger.warning("Shutdown requested but no uvicorn server reference (dev mode)")
```

- Add the endpoints in a new `# ── Health / Shutdown ──` section after the System Status section:

```python
@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Liveness + kernel state. Polled by the Tauri shell and the frontend."""
    return HealthResponse(
        status="ok",
        version=MANAGER_VERSION,
        binary=BinaryStatus(**binary_status.tracker.snapshot()),
    )


@app.post("/api/shutdown")
async def shutdown_endpoint():
    """Graceful shutdown — called by the Tauri shell when the window closes."""
    logger.info("Shutdown requested via API")
    request_shutdown()
    return {"ok": True}
```

- [ ] **Step 4: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): add /api/health and /api/shutdown endpoints"
```

---

### Task 9: Origin check + CORS middleware

Replaces AUTH_TOKEN as the security layer: block browser-originated cross-site writes and WebSocket upgrades against the local port (malicious pages / DNS rebinding). No-Origin clients (curl, Playwright, the Rust health poll) pass untouched.

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_origin.py` (new)

**Interfaces:**
- Produces: `main.DEFAULT_ALLOWED_ORIGINS: list[str]`, `main.ALLOWED_ORIGINS: list[str]` (same list object shared with both middlewares — the Task 10 entry point extends it **in place** for `--allow-origin`).
- Produces: `OriginCheckMiddleware` — 403 on POST/PUT/DELETE/PATCH with a non-whitelisted `Origin`; close-4403 on WebSocket upgrades with a non-whitelisted `Origin`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_origin.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_origin.py -q`
Expected: FAIL — no 403s yet, no CORS headers.

- [ ] **Step 3: Implement**

In `backend/main.py`:
- Re-add `JSONResponse` to the responses import: `from fastapi.responses import JSONResponse`. Add `from fastapi.middleware.cors import CORSMiddleware`. Keep the existing `from starlette.types import ASGIApp, Receive, Scope, Send`.
- Above the `browser_mgr` singleton, add:

```python
# Origins allowed to make state-changing requests / WebSocket upgrades.
# The Tauri WebView origin is http://tauri.localhost on Windows (WebView2)
# and tauri://localhost on macOS/Linux; 5173 covers the Vite dev server.
DEFAULT_ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "tauri://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
# Shared BY REFERENCE with both middlewares; main() extends it in place
# for --allow-origin so runtime additions are visible without a rebuild.
ALLOWED_ORIGINS: list[str] = list(DEFAULT_ALLOWED_ORIGINS)

_WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _scope_origin(scope: Scope) -> str | None:
    for key, val in scope.get("headers", []):
        if key == b"origin":
            return val.decode("latin-1")
    return None


class OriginCheckMiddleware:
    """Reject browser-originated cross-site writes and WebSocket upgrades.

    The backend binds 127.0.0.1 only; this stops malicious web pages (and
    DNS-rebinding hosts) from driving the local API through the user's
    browser. Requests without an Origin header pass through untouched.
    Raw ASGI (not BaseHTTPMiddleware) so WebSocket scopes work.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            origin = _scope_origin(scope)
            if (
                origin is not None
                and scope["method"] in _WRITE_METHODS
                and origin not in ALLOWED_ORIGINS
            ):
                logger.warning("Blocked cross-origin write from %s to %s", origin, scope["path"])
                response = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
                await response(scope, receive, send)
                return
        elif scope["type"] == "websocket":
            origin = _scope_origin(scope)
            if origin is not None and origin not in ALLOWED_ORIGINS:
                logger.warning("Blocked cross-origin WebSocket from %s", origin)
                # ASGI requires receiving websocket.connect before closing
                await receive()
                await send({"type": "websocket.close", "code": 4403, "reason": "Origin not allowed"})
                return
        await self.app(scope, receive, send)
```

- After `app = FastAPI(...)`, register both (CORS added last = outermost, so it answers preflights before the origin check sees them; OPTIONS isn't a write method anyway):

```python
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — existing test_api writes send no Origin header, so they pass the middleware.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_origin.py
git commit -m "feat(backend): origin-check + CORS middleware for local API protection"
```

---

### Task 10: argparse entry point, stdin watchdog, platformdirs defaults

**Files:**
- Modify: `backend/main.py`, `backend/database.py`, `backend/requirements.txt`
- Test: `backend/tests/test_entry.py` (new), `backend/tests/test_database.py`

**Interfaces:**
- Produces: `main.build_arg_parser()` — `--port` (default 8000), `--host` (default 127.0.0.1), `--data-dir` (Path, optional), `--allow-origin` (repeatable).
- Produces: `main.main(argv=None)` — configures db + `CLOAKBROWSER_CACHE_DIR`, extends `ALLOWED_ORIGINS`, starts the stdin watchdog in sidecar mode (`--port` explicitly passed OR frozen), runs a programmatic `uvicorn.Server` stored in `_uvicorn_server`.
- Produces: `db.default_data_dir() -> Path` (platformdirs); `db.DATA_DIR`/`db.DB_PATH` become `Path | None`, lazily configured.

- [ ] **Step 1: Update requirements and install**

`backend/requirements.txt` — add `platformdirs`, and pin cloakbrowser to the version whose API surface (`ensure_binary`, `CLOAKBROWSER_CACHE_DIR`, headed no-viewport behavior) the design doc verified:

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.0
cloakbrowser[geoip]>=0.4.10
websockets>=14.0
httpx>=0.27.0
platformdirs>=4.0
```

```bash
backend/.venv/Scripts/pip install -r backend/requirements.txt
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_entry.py`:

```python
"""Tests for the argparse entry point and stdin watchdog."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend import database as db, main


@pytest.fixture(autouse=True)
def _isolate_entry_side_effects(monkeypatch):
    """main() mutates db globals, ALLOWED_ORIGINS, _uvicorn_server, and env —
    snapshot everything so each test starts clean and leaks nothing."""
    monkeypatch.setattr(db, "DATA_DIR", db.DATA_DIR)
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)
    monkeypatch.setattr(main, "ALLOWED_ORIGINS", list(main.DEFAULT_ALLOWED_ORIGINS))
    monkeypatch.setattr(main, "_uvicorn_server", None)
    # setenv first (captures the original value for restore), then clear it
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", os.environ.get("CLOAKBROWSER_CACHE_DIR", ""))
    monkeypatch.delenv("CLOAKBROWSER_CACHE_DIR", raising=False)


# ── build_arg_parser ─────────────────────────────────────────────────────────


def test_parser_defaults():
    args = main.build_arg_parser().parse_args([])
    assert args.port == 8000
    assert args.host == "127.0.0.1"
    assert args.data_dir is None
    assert args.allow_origin == []


def test_parser_custom_values(tmp_path: Path):
    args = main.build_arg_parser().parse_args([
        "--port", "9000",
        "--host", "0.0.0.0",
        "--data-dir", str(tmp_path),
        "--allow-origin", "http://a.example",
        "--allow-origin", "http://b.example",
    ])
    assert args.port == 9000
    assert args.host == "0.0.0.0"
    assert args.data_dir == tmp_path
    assert args.allow_origin == ["http://a.example", "http://b.example"]


# ── main() wiring ────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_uvicorn(monkeypatch):
    created = {}

    class FakeServer:
        def __init__(self, config):
            created["config"] = config
            self.should_exit = False

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(main.uvicorn, "Server", FakeServer)
    return created


def test_main_configures_everything(fake_uvicorn, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "_start_stdin_watchdog", MagicMock())

    data_dir = tmp_path / "appdata"
    main.main(["--port", "8123", "--data-dir", str(data_dir), "--allow-origin", "http://x.example"])

    assert fake_uvicorn["ran"] is True
    assert fake_uvicorn["config"].port == 8123
    assert fake_uvicorn["config"].host == "127.0.0.1"
    assert db.DB_PATH == data_dir / "profiles.db"
    assert os.environ["CLOAKBROWSER_CACHE_DIR"] == str(data_dir / "chromium-cache")
    assert "http://x.example" in main.ALLOWED_ORIGINS
    assert main._uvicorn_server is not None


def test_main_respects_existing_cache_dir_env(fake_uvicorn, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "_start_stdin_watchdog", MagicMock())
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", "C:/custom-cache")
    main.main(["--data-dir", str(tmp_path)])
    assert os.environ["CLOAKBROWSER_CACHE_DIR"] == "C:/custom-cache"


def test_main_starts_watchdog_only_in_sidecar_mode(fake_uvicorn, monkeypatch, tmp_path: Path):
    watchdog = MagicMock()
    monkeypatch.setattr(main, "_start_stdin_watchdog", watchdog)
    main.main(["--data-dir", str(tmp_path)])  # no --port → not sidecar mode
    watchdog.assert_not_called()
    main.main(["--port", "8124", "--data-dir", str(tmp_path)])  # --port → sidecar
    watchdog.assert_called_once()


# ── stdin watchdog ───────────────────────────────────────────────────────────


def test_stdin_watchdog_triggers_shutdown_on_eof(monkeypatch):
    class FakeBuffer:
        def read(self, n):
            return b""  # immediate EOF

    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(buffer=FakeBuffer()))
    called = []
    monkeypatch.setattr(main, "request_shutdown", lambda: called.append(True))
    main._stdin_watchdog()
    assert called == [True]


def test_stdin_watchdog_survives_read_errors(monkeypatch):
    class FakeBuffer:
        def read(self, n):
            raise OSError("stdin gone")

    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(buffer=FakeBuffer()))
    called = []
    monkeypatch.setattr(main, "request_shutdown", lambda: called.append(True))
    main._stdin_watchdog()
    assert called == [True]
```

Append to `backend/tests/test_database.py`:

```python
def test_default_data_dir_is_cloakbrowser_dir():
    d = db.default_data_dir()
    assert d.is_absolute()
    assert d.name == "CloakBrowser"


def test_lazy_auto_configure(tmp_path: Path, monkeypatch):
    """Without configure(), first DB access falls back to default_data_dir()."""
    monkeypatch.setattr(db, "DATA_DIR", None)
    monkeypatch.setattr(db, "DB_PATH", None)
    monkeypatch.setattr(db, "default_data_dir", lambda: tmp_path / "auto")
    db.init_db()
    assert (tmp_path / "auto" / "profiles.db").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_entry.py backend/tests/test_database.py -q`
Expected: FAIL — `build_arg_parser`, `main`, `_stdin_watchdog`, `default_data_dir` don't exist.

- [ ] **Step 4: Implement database defaults**

In `backend/database.py`, replace the `DATA_DIR = Path("/data")` block and `configure` from Task 1 with:

```python
import platformdirs

# Set by configure() — from --data-dir or default_data_dir(). None until then,
# resolved lazily so `uvicorn backend.main:app` (dev) works without the entry point.
DATA_DIR: Path | None = None
DB_PATH: Path | None = None


def default_data_dir() -> Path:
    """OS-standard app data dir: %LOCALAPPDATA%\\CloakBrowser on Windows,
    ~/Library/Application Support/CloakBrowser on macOS, ~/.local/share/CloakBrowser on Linux."""
    return Path(platformdirs.user_data_dir("CloakBrowser", appauthor=False))


def configure(data_dir: Path | str) -> None:
    """Point the database at a data directory. Call before init_db()."""
    global DATA_DIR, DB_PATH
    DATA_DIR = Path(data_dir)
    DB_PATH = DATA_DIR / "profiles.db"


def _ensure_configured() -> None:
    if DB_PATH is None:
        configure(default_data_dir())
```

Add `_ensure_configured()` as the first statement of `get_db()`, `init_db()`, and `create_profile()` (the latter reads `DATA_DIR` before opening the DB).

- [ ] **Step 5: Implement the entry point**

In `backend/main.py`, add `import argparse`, `import sys`, `import threading` to the stdlib imports (`os` is already imported). Append at the end of the file:

```python
# ── Entry point (sidecar / standalone) ───────────────────────────────────────


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloakbrowser-manager", description="CloakBrowser Manager backend"
    )
    parser.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Data directory (default: OS app-data dir, e.g. %%LOCALAPPDATA%%\\CloakBrowser)",
    )
    parser.add_argument(
        "--allow-origin", action="append", default=[],
        help="Extra allowed Origin for state-changing requests (repeatable)",
    )
    return parser


def _stdin_watchdog() -> None:
    """Block until stdin hits EOF (parent's pipe closed), then shut down.

    The Tauri shell keeps our stdin open for our whole lifetime. If the shell
    crashes or is task-killed, the pipe breaks and we clean up the browsers
    ourselves instead of orphaning them.
    """
    try:
        if sys.stdin is None:
            return
        while sys.stdin.buffer.read(4096):
            pass
    except Exception:
        pass
    logger.info("stdin EOF — parent process gone, shutting down")
    request_shutdown()


def _start_stdin_watchdog() -> None:
    threading.Thread(target=_stdin_watchdog, name="stdin-watchdog", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    global _uvicorn_server

    raw_argv = sys.argv[1:] if argv is None else argv
    args = build_arg_parser().parse_args(raw_argv)

    data_dir = args.data_dir or db.default_data_dir()
    db.configure(data_dir)
    # Keep the Chromium kernel cache inside the app data dir (default is
    # ~/.cloakbrowser). setdefault so an explicit env override wins.
    os.environ.setdefault("CLOAKBROWSER_CACHE_DIR", str(Path(data_dir) / "chromium-cache"))

    # Extend IN PLACE — both middlewares hold a reference to this list.
    ALLOWED_ORIGINS.extend(o for o in args.allow_origin if o not in ALLOWED_ORIGINS)

    # Sidecar mode: an explicit --port (Tauri always passes it) or a frozen
    # binary. Interactive `python -m backend.main` keeps a usable terminal.
    if "--port" in raw_argv or getattr(sys, "frozen", False):
        _start_stdin_watchdog()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.run()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()  # required for PyInstaller onefile
    main()
```

- [ ] **Step 6: Run the full suite**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 7: Manual smoke — source-mode sidecar**

```bash
backend/.venv/Scripts/python.exe -m backend.main --port 8000 --data-dir "$TEMP/cloak-dev-smoke" &
sleep 3
curl -s http://127.0.0.1:8000/api/health
curl -s -X POST http://127.0.0.1:8000/api/shutdown
```

Expected: health returns `{"status":"ok","version":"0.1.0","binary":{...}}` (state `downloading` or `ready` depending on network); the shutdown call terminates the process; `$TEMP/cloak-dev-smoke/profiles.db` exists.

- [ ] **Step 8: Commit**

```bash
git add backend/main.py backend/database.py backend/requirements.txt backend/tests
git commit -m "feat(backend): argparse entry with stdin watchdog, platformdirs data dir, kernel cache env"
```

---

## Milestone 2 — PyInstaller sidecar

### Task 11: build.py — freeze the backend for Tauri

**Files:**
- Create: `backend/build.py`, `backend/sidecar_entry.py`, `backend/requirements-dev.txt`
- Test: `backend/tests/test_build.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `frontend/src-tauri/bin/server-<target-triple>.exe` — the exact name Tauri's `externalBin: ["bin/server"]` resolves (e.g. `server-x86_64-pc-windows-msvc.exe`). Tasks 12-13 depend on this file existing.
- Produces: `build.target_triple() -> str`.

- [ ] **Step 1: Dev requirements**

Create `backend/requirements-dev.txt`:

```
pytest>=8.0
pytest-asyncio>=0.24
pyinstaller>=6.11
```

```bash
backend/.venv/Scripts/pip install -r backend/requirements-dev.txt
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_build.py`:

```python
"""Tests for the PyInstaller build helper (pure functions only)."""

from __future__ import annotations

from backend.build import target_triple


def test_target_triple_shape():
    triple = target_triple()
    # e.g. x86_64-pc-windows-msvc / aarch64-apple-darwin / x86_64-unknown-linux-gnu
    parts = triple.split("-")
    assert len(parts) >= 3
    assert parts[0] in ("x86_64", "aarch64")
```

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_build.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.build'`

- [ ] **Step 3: Write the entry wrapper and build script**

Create `backend/sidecar_entry.py` (PyInstaller can't use `backend/main.py` directly — it does relative imports):

```python
"""PyInstaller entry point — imports the backend package absolutely."""

import multiprocessing

from backend.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

Create `backend/build.py`:

```python
"""Build the PyInstaller sidecar and install it where Tauri expects it.

Usage (from repo root):
    backend/.venv/Scripts/python.exe backend/build.py

Produces backend/dist/server(.exe) and copies it to
frontend/src-tauri/bin/server-<target-triple>(.exe) for Tauri's externalBin.

The CloakBrowser Chromium kernel is NOT bundled (BINARY-LICENSE.md forbids
redistribution) — the frozen backend downloads it on first run.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TAURI_BIN = REPO_ROOT / "frontend" / "src-tauri" / "bin"


def target_triple() -> str:
    """Host target triple — ask rustc, fall back to platform-derived."""
    try:
        out = subprocess.run(
            ["rustc", "-Vv"], capture_output=True, text=True, check=True
        ).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split()[1]
    except (OSError, subprocess.CalledProcessError):
        pass
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[
        platform.machine().lower()
    ]
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def crypto_collect_args() -> list[str]:
    """Collect whichever signature-verification lib cloakbrowser installed —
    Ed25519 verification of the kernel download must work when frozen."""
    args: list[str] = []
    for pkg in ("cryptography", "nacl"):
        if importlib.util.find_spec(pkg) is not None:
            args += ["--collect-all", pkg]
    return args


def main() -> None:
    ext = ".exe" if sys.platform == "win32" else ""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        # onefile matches Tauri's single-file sidecar model. Escape hatch if
        # cold start or AV false-positives bite: switch to --onedir and bundle
        # the directory as Tauri resources instead of externalBin.
        "--onefile",
        "--name", "server",
        "--distpath", str(BACKEND / "dist"),
        "--workpath", str(BACKEND / "build"),
        "--specpath", str(BACKEND),
        "--paths", str(REPO_ROOT),
        "--collect-all", "cloakbrowser",   # geoip data + pinned signing pubkey
        "--collect-all", "playwright",     # node driver — the easiest miss
        "--collect-all", "uvicorn",        # uvicorn.logging + loop/proto submodules
        "--collect-all", "websockets",
        *crypto_collect_args(),
        str(BACKEND / "sidecar_entry.py"),
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

    built = BACKEND / "dist" / f"server{ext}"
    if not built.exists():
        sys.exit(f"PyInstaller did not produce {built}")

    TAURI_BIN.mkdir(parents=True, exist_ok=True)
    dest = TAURI_BIN / f"server-{target_triple()}{ext}"
    shutil.copy2(built, dest)
    print(f"sidecar installed: {dest}")


if __name__ == "__main__":
    main()
```

Append to `.gitignore`:

```
# PyInstaller sidecar
backend/build/
backend/dist/
backend/*.spec

# Tauri
frontend/src-tauri/target/
frontend/src-tauri/gen/
frontend/src-tauri/bin/
```

- [ ] **Step 4: Run the unit test, then the real build**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_build.py -q`
Expected: PASS

Run: `backend/.venv/Scripts/python.exe backend/build.py`
Expected: PyInstaller finishes; `frontend/src-tauri/bin/server-x86_64-pc-windows-msvc.exe` exists (name printed at the end). First build takes several minutes.

- [ ] **Step 5: Smoke the frozen sidecar**

```bash
SMOKE_DIR="$TEMP/cloak-sidecar-smoke"
rm -rf "$SMOKE_DIR"
frontend/src-tauri/bin/server-x86_64-pc-windows-msvc.exe --port 8125 --data-dir "$SMOKE_DIR" &
sleep 8   # onefile cold start is slow
curl -s http://127.0.0.1:8125/api/health
curl -s -X POST http://127.0.0.1:8125/api/shutdown
```

Expected:
- health returns `{"status":"ok","version":"0.1.0","binary":{"state":"downloading"...}}` (or `ready` if the kernel cache already exists).
- After shutdown the process exits (check `tasklist | grep -i server` is empty).
- `$SMOKE_DIR/profiles.db` exists and `$SMOKE_DIR/chromium-cache/` is where kernel files land — **NOT** inside a `_MEI*` temp dir (this validates `CLOAKBROWSER_CACHE_DIR` in frozen mode; let the download run a few seconds before shutdown to see the dir appear).

If the frozen exe crashes on startup with `ModuleNotFoundError`, add the missing package as another `--collect-all` in `build.py` — that is the known PyInstaller failure mode for this stack.

- [ ] **Step 6: Commit**

```bash
git add backend/build.py backend/sidecar_entry.py backend/requirements-dev.txt backend/tests/test_build.py .gitignore
git commit -m "feat(build): PyInstaller sidecar build script with target-triple install"
```

---

## Milestone 3 — Tauri shell (Rust)

### Task 12: Scaffold the Tauri v2 project

**Files:**
- Create: `frontend/src-tauri/` (tauri.conf.json, Cargo.toml, build.rs, capabilities/default.json, src/main.rs, src/lib.rs, icons/ from scaffold)
- Modify: `frontend/package.json`

**Prerequisite check:** `rustc -V` must print 1.77+. If missing: install rustup + MSVC Build Tools (`winget install Rustlang.Rustup`), then restart the shell.

- [ ] **Step 1: Add Tauri deps and scaffold**

From `frontend/`:

```bash
pnpm add -D @tauri-apps/cli@^2
pnpm add @tauri-apps/api@^2
pnpm build   # ensure ../dist exists — tauri's generate_context! needs frontendDist present
pnpm tauri init --ci --app-name cloakbrowser-manager --window-title "CloakBrowser Manager" \
  --frontend-dist ../dist --dev-url http://localhost:5173 \
  --before-dev-command "pnpm dev" --before-build-command "pnpm build"
```

Add to `frontend/package.json` scripts: `"tauri": "tauri"`.

- [ ] **Step 2: Replace the generated config with ours**

Overwrite `frontend/src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "CloakBrowser Manager",
  "version": "0.1.0",
  "identifier": "com.cloakbrowser.manager",
  "build": {
    "beforeDevCommand": "pnpm dev",
    "devUrl": "http://localhost:5173",
    "beforeBuildCommand": "pnpm build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "CloakBrowser Manager",
        "width": 1280,
        "height": 800
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "externalBin": ["bin/server"],
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ]
  }
}
```

(Keep the scaffold-generated `icons/`. `externalBin: ["bin/server"]` resolves the Task 11 artifact `bin/server-x86_64-pc-windows-msvc.exe` — if the CLI errors that it is missing, re-run `backend/build.py`.)

Overwrite `frontend/src-tauri/Cargo.toml`:

```toml
[package]
name = "cloakbrowser-manager"
version = "0.1.0"
description = "CloakBrowser profile manager desktop client"
edition = "2021"

[lib]
name = "cloakbrowser_manager_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"
tauri-plugin-single-instance = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ureq = "2"
```

(`ureq` is the blocking HTTP client for health polling and the shutdown POST — no tokio/reqwest weight. Commit `Cargo.lock` — this is an application.)

`frontend/src-tauri/build.rs` (keep scaffold version; it should be exactly):

```rust
fn main() {
    tauri_build::build()
}
```

Create `frontend/src-tauri/capabilities/default.json` (custom app commands need no extra permissions; `core:default` covers events + invoke):

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Main window capabilities",
  "windows": ["main"],
  "permissions": ["core:default"]
}
```

Overwrite `frontend/src-tauri/src/main.rs`:

```rust
// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    cloakbrowser_manager_lib::run()
}
```

Overwrite `frontend/src-tauri/src/lib.rs` with a minimal stub (Task 13 fills it in):

```rust
use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 3: Verify it compiles and opens**

Run: `cargo check --manifest-path frontend/src-tauri/Cargo.toml`
Expected: compiles clean (first run downloads crates, several minutes).

Run: `pnpm tauri dev` (from `frontend/`)
Expected: a desktop window opens rendering the current web UI (it will show the "Unable to reach the server" error screen — the backend isn't spawned yet and auth endpoints are gone; that's expected until Tasks 13/15). Close the window; the process exits.

- [ ] **Step 4: Commit**

```bash
git add frontend/src-tauri frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat(tauri): scaffold Tauri v2 shell with single-instance and sidecar config"
```

---

### Task 13: Rust backend supervision (spawn, health, events, shutdown)

**Files:**
- Modify: `frontend/src-tauri/src/lib.rs` (complete rewrite of the stub)

**Interfaces (consumed by the frontend in Task 14):**
- Commands: `probe_port(port: u16) -> bool`, `get_backend_state() -> BackendSnapshot`, `save_port(port: u16)`, `restart_backend()`.
- Events: `backend-starting` / `port-conflict` / `backend-ready` / `backend-error`, each carrying the full `BackendSnapshot` payload: `{ state: "starting"|"port-conflict"|"ready"|"error", port: number, message: string|null }`.
- Deviations from the design doc, both deliberate: (1) Rust does **not** pass `--data-dir` — §6.1 makes platformdirs the backend-side default and single source of truth; `--data-dir` stays a dev/test escape hatch. (2) The port probe **binds** instead of connecting — the backend needs to *bind* the port, and bind-probing also catches TIME_WAIT/non-listening binds.

- [ ] **Step 1: Write lib.rs in full**

Replace `frontend/src-tauri/src/lib.rs`:

```rust
use std::fs;
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const DEFAULT_PORT: u16 = 8000;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Clone, Serialize)]
pub struct BackendSnapshot {
    pub state: String, // "starting" | "port-conflict" | "ready" | "error"
    pub port: u16,
    pub message: Option<String>,
}

impl Default for BackendSnapshot {
    fn default() -> Self {
        Self { state: "starting".into(), port: DEFAULT_PORT, message: None }
    }
}

#[derive(Default)]
pub struct BackendState {
    snapshot: Mutex<BackendSnapshot>,
    child: Mutex<Option<CommandChild>>,
    child_exited: Arc<AtomicBool>,
    shutting_down: Arc<AtomicBool>,
}

#[derive(Serialize, Deserialize)]
struct AppConfig {
    port: u16,
}

fn config_path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_config_dir()
        .expect("app_config_dir unavailable")
        .join("config.json")
}

fn read_port(app: &AppHandle) -> u16 {
    fs::read_to_string(config_path(app))
        .ok()
        .and_then(|s| serde_json::from_str::<AppConfig>(&s).ok())
        .map(|c| c.port)
        .unwrap_or(DEFAULT_PORT)
}

fn write_port(app: &AppHandle, port: u16) -> Result<(), String> {
    let path = config_path(app);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(&AppConfig { port }).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}

pub fn port_is_free(port: u16) -> bool {
    // Bind, not connect: the backend needs to BIND this port, and binding
    // also detects TIME_WAIT leftovers that a connect probe would miss.
    TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port)).is_ok()
}

/// Update the shared snapshot and broadcast it as an event. The frontend
/// also pulls the snapshot via get_backend_state on startup, so events
/// emitted before its listeners attach are never lost.
fn set_snapshot(app: &AppHandle, state: &str, port: u16, message: Option<String>) {
    let snap = BackendSnapshot { state: state.into(), port, message };
    {
        let st = app.state::<BackendState>();
        *st.snapshot.lock().unwrap() = snap.clone();
    }
    let event = match state {
        "port-conflict" => "port-conflict",
        "ready" => "backend-ready",
        "error" => "backend-error",
        _ => "backend-starting",
    };
    let _ = app.emit(event, snap);
}

fn spawn_backend(app: &AppHandle, port: u16) -> Result<CommandChild, String> {
    let port_arg = port.to_string();

    let cmd = if cfg!(debug_assertions) {
        // Dev: run the Python backend from source so `tauri dev` doesn't
        // require a PyInstaller build on every iteration.
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")); // .../frontend/src-tauri
        let repo_root = manifest
            .parent()
            .and_then(|p| p.parent())
            .expect("repo root")
            .to_path_buf();
        let venv_python = repo_root.join("backend/.venv/Scripts/python.exe");
        let python = if venv_python.exists() {
            venv_python.to_string_lossy().into_owned()
        } else {
            "python".to_string()
        };
        app.shell()
            .command(python)
            .args(["-m", "backend.main", "--port", &port_arg])
            .current_dir(repo_root)
    } else {
        app.shell()
            .sidecar("server")
            .map_err(|e| e.to_string())?
            .args(["--port", &port_arg])
    };

    // stdin stays piped and open for the child's lifetime — it closing is the
    // backend's watchdog signal to shut itself down if this shell dies.
    let (mut rx, child) = cmd.spawn().map_err(|e| e.to_string())?;

    let state = app.state::<BackendState>();
    state.child_exited.store(false, Ordering::SeqCst);
    let exited = state.child_exited.clone();
    let shutting_down = state.shutting_down.clone();

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    println!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    exited.store(true, Ordering::SeqCst);
                    if !shutting_down.load(Ordering::SeqCst) {
                        let port = app_handle
                            .state::<BackendState>()
                            .snapshot
                            .lock()
                            .unwrap()
                            .port;
                        set_snapshot(
                            &app_handle,
                            "error",
                            port,
                            Some(format!("backend exited unexpectedly (code {:?})", payload.code)),
                        );
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(child)
}

/// Full startup flow: read configured port → probe → spawn → poll health.
/// Runs on its own thread; progress lands in the snapshot + events.
pub fn start_backend(app: AppHandle) {
    std::thread::spawn(move || {
        let port = read_port(&app);
        set_snapshot(&app, "starting", port, None);

        if !port_is_free(port) {
            set_snapshot(&app, "port-conflict", port, None);
            return;
        }

        let child = match spawn_backend(&app, port) {
            Ok(c) => c,
            Err(e) => {
                set_snapshot(&app, "error", port, Some(format!("failed to spawn backend: {e}")));
                return;
            }
        };
        {
            let state = app.state::<BackendState>();
            *state.child.lock().unwrap() = Some(child);
        }

        let url = format!("http://127.0.0.1:{port}/api/health");
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        loop {
            if app.state::<BackendState>().child_exited.load(Ordering::SeqCst) {
                return; // Terminated handler already reported the error
            }
            if Instant::now() > deadline {
                set_snapshot(
                    &app,
                    "error",
                    port,
                    Some("backend did not become healthy within 30s".into()),
                );
                return;
            }
            match ureq::get(&url).timeout(Duration::from_secs(2)).call() {
                Ok(resp) if resp.status() == 200 => break,
                _ => std::thread::sleep(Duration::from_millis(500)),
            }
        }
        set_snapshot(&app, "ready", port, None);
    });
}

/// Graceful teardown: POST /api/shutdown (backend closes every browser
/// context so session data flushes), wait up to 10s, then hard-kill.
fn shutdown_backend(app: &AppHandle) {
    let state = app.state::<BackendState>();
    state.shutting_down.store(true, Ordering::SeqCst);
    let child = state.child.lock().unwrap().take();
    let Some(child) = child else { return };

    let port = state.snapshot.lock().unwrap().port;
    let _ = ureq::post(&format!("http://127.0.0.1:{port}/api/shutdown"))
        .timeout(Duration::from_secs(3))
        .send_string("");

    let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
    while Instant::now() < deadline {
        if state.child_exited.load(Ordering::SeqCst) {
            return;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    println!("[shell] backend did not exit in time — killing");
    let _ = child.kill();
}

#[tauri::command]
fn probe_port(port: u16) -> bool {
    port_is_free(port)
}

#[tauri::command]
fn get_backend_state(state: State<'_, BackendState>) -> BackendSnapshot {
    state.snapshot.lock().unwrap().clone()
}

#[tauri::command]
async fn save_port(app: AppHandle, port: u16) -> Result<(), String> {
    write_port(&app, port)?;
    restart_backend(app).await
}

#[tauri::command]
async fn restart_backend(app: AppHandle) -> Result<(), String> {
    // Async command → runs off the main thread; blocking here is fine.
    shutdown_backend(&app);
    let state = app.state::<BackendState>();
    state.shutting_down.store(false, Ordering::SeqCst);
    start_backend(app.clone());
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Second launch: focus the existing window instead.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .invoke_handler(tauri::generate_handler![
            probe_port,
            get_backend_state,
            save_port,
            restart_backend
        ])
        .setup(|app| {
            start_backend(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                shutdown_backend(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_detects_bound_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(!port_is_free(port));
        drop(listener);
        assert!(port_is_free(port));
    }
}
```

- [ ] **Step 2: Run the Rust tests**

Run: `cargo test --manifest-path frontend/src-tauri/Cargo.toml`
Expected: `probe_detects_bound_port ... ok`

- [ ] **Step 3: Manual verification with tauri dev**

Run: `pnpm tauri dev` (from `frontend/`)
Expected in the terminal: `[backend]` log lines from the spawned Python process (uvicorn startup). The window still shows the old UI's error screen (frontend cutover is Task 15) — but `curl http://127.0.0.1:8000/api/health` from another terminal returns 200 while the app is open. Close the window: the Python process must disappear from `tasklist` within ~10s (graceful shutdown path).

Also verify the watchdog: start `pnpm tauri dev`, then kill the Tauri process from Task Manager (not the console) — the Python process must exit by itself within a few seconds (stdin EOF).

- [ ] **Step 4: Commit**

```bash
git add frontend/src-tauri
git commit -m "feat(tauri): supervise Python sidecar — spawn, health poll, events, graceful shutdown"
```

---

## Milestone 4 — Frontend bootstrap & cutover

### Task 14: Bootstrap infrastructure (additive — old UI keeps working)

**Files:**
- Create: `frontend/src/bootstrap/tauri.ts`, `frontend/src/bootstrap/useBootstrap.ts`, `frontend/src/bootstrap/PortConfigModal.tsx`, `frontend/src/bootstrap/DownloadingScreen.tsx`, `frontend/src/bootstrap/BackendErrorScreen.tsx`
- Modify: `frontend/src/lib/api.ts` (additive only), `frontend/vite.config.ts`
- Test: `frontend/src/bootstrap/useBootstrap.test.ts`, `frontend/src/lib/api.test.ts` (additive)

**Interfaces:**
- Consumes: Rust commands/events from Task 13 (`get_backend_state`, `probe_port`, `save_port`, `restart_backend`; `BackendSnapshot` payloads).
- Produces: `useBootstrap() -> { state: BootstrapPhase, probePort(port), savePort(port), retry() }` where `BootstrapPhase.phase ∈ detecting | port-conflict | waiting-backend | downloading-binary | ready | backend-error`.
- Produces: `setApiBase(url)` / `getApiBase()` in `lib/api.ts`; `api.health() -> Health`.

- [ ] **Step 1: api.ts additions**

In `frontend/src/lib/api.ts` — do **not** remove anything yet (App.tsx still uses auth/clipboard until Task 15). Add below the `ApiError` class:

```ts
// Base URL for all requests. "" in web dev (Vite proxies /api); set to
// "http://127.0.0.1:{port}" by the bootstrap layer under Tauri.
let _base = "";

export function setApiBase(url: string) {
  _base = url.replace(/\/+$/, "");
}

export function getApiBase(): string {
  return _base;
}
```

Change the `fetch(path, {...})` call in `request()` to `fetch(_base + path, {...})`. Add the types and endpoint:

```ts
export interface BinaryStatus {
  state: "downloading" | "ready" | "error";
  version: string | null;
  error: string | null;
}

export interface Health {
  status: string;
  version: string;
  binary: BinaryStatus;
}
```

In the `api` object: `health: () => request<Health>("/api/health"),`

In `frontend/vite.config.ts`, change the proxy target to the new default dev port:

```ts
    proxy: {
      "/api": "http://localhost:8000",
    },
```

Install the Tauri JS API (from `frontend/`): `pnpm add @tauri-apps/api@^2` (no-op if Task 12 already added it).

- [ ] **Step 2: tauri.ts wrapper**

Create `frontend/src/bootstrap/tauri.ts`:

```ts
/**
 * Thin wrappers around @tauri-apps/api so the app also runs in a plain
 * browser (pnpm dev) where the Tauri IPC bridge doesn't exist. Dynamic
 * imports keep Tauri modules out of the pure-web bundle path at runtime.
 */

export interface BackendSnapshot {
  state: "starting" | "port-conflict" | "ready" | "error";
  port: number;
  message: string | null;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function listen<T>(
  event: string,
  handler: (payload: T) => void,
): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<T>(event, (e) => handler(e.payload));
}

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}
```

- [ ] **Step 3: Write the failing hook tests**

Create `frontend/src/bootstrap/useBootstrap.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useBootstrap } from "./useBootstrap";
import type { BackendSnapshot } from "./tauri";

vi.mock("./tauri", () => ({
  isTauri: vi.fn(),
  invoke: vi.fn(),
  listen: vi.fn(),
}));
vi.mock("../lib/api", () => ({
  api: { health: vi.fn() },
  setApiBase: vi.fn(),
}));

import { isTauri, invoke, listen } from "./tauri";
import { api, setApiBase } from "../lib/api";

const mockIsTauri = vi.mocked(isTauri);
const mockInvoke = vi.mocked(invoke);
const mockListen = vi.mocked(listen);
const mockHealth = vi.mocked(api.health);

let handlers: Record<string, (payload: BackendSnapshot) => void>;

beforeEach(() => {
  vi.clearAllMocks();
  handlers = {};
  mockListen.mockImplementation(async (event: string, cb: (p: never) => void) => {
    handlers[event] = cb as (payload: BackendSnapshot) => void;
    return () => {};
  });
});

describe("useBootstrap outside Tauri", () => {
  it("goes straight to ready with a relative api base", async () => {
    mockIsTauri.mockReturnValue(false);
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.state.phase).toBe("ready"));
    expect(setApiBase).toHaveBeenCalledWith("");
    expect(mockListen).not.toHaveBeenCalled();
  });
});

describe("useBootstrap inside Tauri", () => {
  beforeEach(() => {
    mockIsTauri.mockReturnValue(true);
  });

  it("shows port conflict from the initial snapshot", async () => {
    mockInvoke.mockResolvedValue({ state: "port-conflict", port: 8000, message: null });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "port-conflict", port: 8000 }),
    );
  });

  it("sets api base on backend-ready, then polls health to ready", async () => {
    mockInvoke.mockResolvedValue({ state: "starting", port: 8000, message: null });
    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "downloading", version: null, error: null },
    });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(handlers["backend-ready"]).toBeDefined());

    await act(async () => {
      handlers["backend-ready"]({ state: "ready", port: 8123, message: null });
    });
    expect(setApiBase).toHaveBeenCalledWith("http://127.0.0.1:8123");
    await waitFor(() => expect(result.current.state.phase).toBe("downloading-binary"));

    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "ready", version: "135.0", error: null },
    });
    await waitFor(() => expect(result.current.state.phase).toBe("ready"), { timeout: 3000 });
  });

  it("surfaces kernel download errors from health", async () => {
    mockInvoke.mockResolvedValue({ state: "ready", port: 8000, message: null });
    mockHealth.mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      binary: { state: "error", version: null, error: "disk full" },
    });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "backend-error", message: "disk full" }),
    );
  });

  it("shows backend error and retries via restart_backend", async () => {
    mockInvoke.mockResolvedValue({ state: "error", port: 8000, message: "spawn failed" });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "backend-error", message: "spawn failed" }),
    );

    mockInvoke.mockClear();
    mockInvoke.mockResolvedValue(undefined as never);
    await act(async () => {
      await result.current.retry();
    });
    expect(mockInvoke).toHaveBeenCalledWith("restart_backend");
    expect(result.current.state.phase).toBe("waiting-backend");
  });

  it("savePort invokes save_port and waits for the backend", async () => {
    mockInvoke.mockResolvedValue({ state: "port-conflict", port: 8000, message: null });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.state.phase).toBe("port-conflict"));

    mockInvoke.mockClear();
    mockInvoke.mockResolvedValue(undefined as never);
    await act(async () => {
      await result.current.savePort(8001);
    });
    expect(mockInvoke).toHaveBeenCalledWith("save_port", { port: 8001 });
    expect(result.current.state.phase).toBe("waiting-backend");
  });
});
```

Run: `pnpm vitest run src/bootstrap/useBootstrap.test.ts`
Expected: FAIL — `useBootstrap.ts` doesn't exist.

- [ ] **Step 4: Implement the hook**

Create `frontend/src/bootstrap/useBootstrap.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { api, setApiBase } from "../lib/api";
import { invoke, isTauri, listen, type BackendSnapshot } from "./tauri";

export type BootstrapPhase =
  | { phase: "detecting" }
  | { phase: "port-conflict"; port: number }
  | { phase: "waiting-backend" }
  | { phase: "downloading-binary" }
  | { phase: "ready" }
  | { phase: "backend-error"; message: string };

const HEALTH_POLL_MS = 1000;

/**
 * Startup state machine. Outside Tauri (pnpm dev) it short-circuits to
 * ready with a relative api base. Inside Tauri it follows the Rust shell:
 * events for live updates + a get_backend_state snapshot to catch anything
 * emitted before our listeners attached.
 */
export function useBootstrap() {
  const [state, setState] = useState<BootstrapPhase>({ phase: "detecting" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Backend reachable → wait until the Chromium kernel is ready too.
  const startHealthPolling = useCallback(() => {
    stopPolling();
    const tick = async () => {
      try {
        const health = await api.health();
        if (health.binary.state === "ready") {
          stopPolling();
          setState({ phase: "ready" });
        } else if (health.binary.state === "error") {
          stopPolling();
          setState({
            phase: "backend-error",
            message: health.binary.error ?? "Browser core download failed",
          });
        } else {
          setState({ phase: "downloading-binary" });
        }
      } catch {
        // transient — keep polling; the Rust shell reports hard failures
      }
    };
    void tick();
    pollRef.current = setInterval(tick, HEALTH_POLL_MS);
  }, [stopPolling]);

  const applySnapshot = useCallback(
    (snap: BackendSnapshot) => {
      if (snap.state === "port-conflict") {
        stopPolling();
        setState({ phase: "port-conflict", port: snap.port });
      } else if (snap.state === "error") {
        stopPolling();
        setState({ phase: "backend-error", message: snap.message ?? "Backend failed to start" });
      } else if (snap.state === "ready") {
        setApiBase(`http://127.0.0.1:${snap.port}`);
        setState({ phase: "waiting-backend" });
        startHealthPolling();
      } else {
        setState({ phase: "waiting-backend" });
      }
    },
    [startHealthPolling, stopPolling],
  );

  useEffect(() => {
    if (!isTauri()) {
      // Plain web dev: relative base, Vite proxies /api → localhost:8000.
      setApiBase("");
      setState({ phase: "ready" });
      return;
    }
    let disposed = false;
    const unlistens: Array<() => void> = [];
    (async () => {
      for (const event of ["backend-starting", "port-conflict", "backend-ready", "backend-error"]) {
        const un = await listen<BackendSnapshot>(event, (snap) => {
          if (!disposed) applySnapshot(snap);
        });
        unlistens.push(un);
      }
      // Catch up on state set before our listeners attached.
      const snap = await invoke<BackendSnapshot>("get_backend_state");
      if (!disposed) applySnapshot(snap);
    })();
    return () => {
      disposed = true;
      unlistens.forEach((un) => un());
      stopPolling();
    };
  }, [applySnapshot, stopPolling]);

  const probePort = useCallback((port: number) => invoke<boolean>("probe_port", { port }), []);

  const savePort = useCallback(async (port: number) => {
    await invoke("save_port", { port });
    setState({ phase: "waiting-backend" });
  }, []);

  const retry = useCallback(async () => {
    setState({ phase: "waiting-backend" });
    await invoke("restart_backend");
  }, []);

  return { state, probePort, savePort, retry };
}
```

- [ ] **Step 5: The three screens**

Create `frontend/src/bootstrap/PortConfigModal.tsx`:

```tsx
import { AlertTriangle } from "lucide-react";
import { useState } from "react";

interface PortConfigModalProps {
  port: number; // the port that was found occupied
  onProbe: (port: number) => Promise<boolean>;
  onSave: (port: number) => Promise<void>;
}

export function PortConfigModal({ port, onProbe, onSave }: PortConfigModalProps) {
  const [value, setValue] = useState(String(port));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const candidate = Number(value);
    if (!Number.isInteger(candidate) || candidate < 1024 || candidate > 65535) {
      setError("Enter a port between 1024 and 65535");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const free = await onProbe(candidate);
      if (!free) {
        setError(`Port ${candidate} is also in use — try another`);
        return;
      }
      await onSave(candidate);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <form onSubmit={handleSubmit} className="w-96 p-6 rounded-lg border border-border bg-surface-1">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold">Port {port} is in use</h2>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Another program is using the API port. Choose a different port for the backend.
        </p>
        <label className="label">API Port</label>
        <input
          className="input"
          type="number"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          min={1024}
          max={65535}
        />
        {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
        <button type="submit" disabled={busy} className="btn-primary w-full mt-4">
          {busy ? "Checking..." : "Use this port"}
        </button>
      </form>
    </div>
  );
}
```

Create `frontend/src/bootstrap/DownloadingScreen.tsx`:

```tsx
import { Loader2 } from "lucide-react";

interface DownloadingScreenProps {
  message: string;
}

export function DownloadingScreen({ message }: DownloadingScreenProps) {
  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="text-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent mx-auto mb-3" />
        <p className="text-sm text-gray-300">{message}</p>
        <p className="text-xs text-gray-500 mt-1">This can take a few minutes on first run</p>
      </div>
    </div>
  );
}
```

Create `frontend/src/bootstrap/BackendErrorScreen.tsx`:

```tsx
import { AlertCircle } from "lucide-react";

interface BackendErrorScreenProps {
  message: string;
  onRetry: () => void;
}

export function BackendErrorScreen({ message, onRetry }: BackendErrorScreenProps) {
  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="text-center max-w-md px-6">
        <AlertCircle className="h-6 w-6 text-red-400 mx-auto mb-3" />
        <p className="text-sm text-red-400 mb-1">Backend error</p>
        <p className="text-xs text-gray-500 break-words mb-4">{message}</p>
        <button onClick={onRetry} className="btn-secondary">
          Retry
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: api.test.ts additions**

Append to `frontend/src/lib/api.test.ts` (import `setApiBase` alongside `api`):

```ts
// ── setApiBase ──────────────────────────────────────────────────────────────

describe("setApiBase", () => {
  it("prefixes all requests with the base URL", async () => {
    setApiBase("http://127.0.0.1:9999");
    mockFetch.mockResolvedValueOnce(jsonResponse([]));
    await api.listProfiles();
    expect(mockFetch.mock.calls[0][0]).toBe("http://127.0.0.1:9999/api/profiles");
    setApiBase("");
  });
});

// ── health ──────────────────────────────────────────────────────────────────

describe("api.health", () => {
  it("fetches /api/health", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        version: "0.1.0",
        binary: { state: "ready", version: "135.0", error: null },
      }),
    );
    const h = await api.health();
    expect(h.binary.state).toBe("ready");
    expect(mockFetch.mock.calls[0][0]).toBe("/api/health");
  });
});
```

- [ ] **Step 7: Run all frontend tests and the build**

Run: `pnpm test` then `pnpm build` (from `frontend/`)
Expected: PASS / compiles. Old App/api surface untouched, so nothing else breaks.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/bootstrap frontend/src/lib frontend/vite.config.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat(frontend): bootstrap state machine, port modal, download/error screens"
```

---

### Task 15: Frontend cutover — wire bootstrap, remove VNC viewer and login

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/lib/api.ts`, `frontend/src/components/ProfileForm.tsx`, `frontend/package.json`
- Create: `frontend/src/components/CdpCopyButton.tsx`
- Test: `frontend/src/components/CdpCopyButton.test.tsx`; adapt `frontend/src/lib/api.test.ts`, `frontend/src/hooks/useProfiles.test.ts`
- Delete: `frontend/src/components/ProfileViewer.tsx`, `frontend/src/components/LoginPage.tsx`, `frontend/src/novnc.d.ts`

- [ ] **Step 1: Delete VNC/login files and the noVNC dependency**

```bash
git rm frontend/src/components/ProfileViewer.tsx frontend/src/components/LoginPage.tsx frontend/src/novnc.d.ts
cd frontend && pnpm remove @novnc/novnc
```

- [ ] **Step 2: Converge api.ts**

In `frontend/src/lib/api.ts`:
- `Profile`: delete `clipboard_sync: boolean;` and `vnc_ws_port: number | null;`.
- `ProfileCreateData`: delete `clipboard_sync?: boolean;`.
- Replace `LaunchResult`:

```ts
export interface LaunchResult {
  profile_id: string;
  status: string;
  cdp_url: string | null;
}
```

- Delete the `_onUnauthorized` global, `setOnUnauthorized`, and the 401 branch inside `request()` (keep the generic error path).
- Delete from the `api` object: `authStatus`, `login`, `logout`, `setClipboard`, `getClipboard`.

- [ ] **Step 3: Rewrite App.tsx**

Replace `frontend/src/App.tsx` in full:

```tsx
import { useState, useCallback } from "react";
import { PanelLeftClose, PanelLeft } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { type ProfileCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { useBootstrap } from "./bootstrap/useBootstrap";
import { PortConfigModal } from "./bootstrap/PortConfigModal";
import { DownloadingScreen } from "./bootstrap/DownloadingScreen";
import { BackendErrorScreen } from "./bootstrap/BackendErrorScreen";

type View = "empty" | "create" | "edit";

export default function App() {
  const { state, probePort, savePort, retry } = useBootstrap();

  switch (state.phase) {
    case "detecting":
      return (
        <div className="h-screen flex items-center justify-center">
          <div className="text-gray-500 text-sm">Loading...</div>
        </div>
      );
    case "port-conflict":
      return <PortConfigModal port={state.port} onProbe={probePort} onSave={savePort} />;
    case "waiting-backend":
      return <DownloadingScreen message="Starting backend service..." />;
    case "downloading-binary":
      return <DownloadingScreen message="Downloading browser core..." />;
    case "backend-error":
      return <BackendErrorScreen message={state.message} onRetry={retry} />;
    case "ready":
      return <AppContent />;
  }
}

function AppContent() {
  const { profiles, loading, error, create, update, remove, launch, stop } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setView("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    await update(selectedId, data);
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    await launch(selectedId);
  }, [selectedId, launch]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
  }, [selectedId, stop]);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
                <span className="text-xs text-gray-500 capitalize">{selected.platform}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {view === "empty" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <p className="text-gray-500 text-sm">Select a profile or create a new one</p>
              </div>
            </div>
          )}

          {view === "create" && (
            <ProfileForm
              profile={null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
            />
          )}

          {view === "edit" && selected && (
            <ProfileForm
              profile={selected}
              onSave={handleUpdate}
              onDelete={handleDelete}
              onCancel={() => {
                setSelectedId(null);
                setView("empty");
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: CDP copy button (test first)**

Create `frontend/src/components/CdpCopyButton.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { CdpCopyButton } from "./CdpCopyButton";
import { setApiBase } from "../lib/api";

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  writeText.mockClear();
});

describe("CdpCopyButton", () => {
  it("copies the absolute CDP URL and confirms", async () => {
    setApiBase("http://127.0.0.1:8123");
    render(<CdpCopyButton cdpUrl="/api/profiles/abc/cdp" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("http://127.0.0.1:8123/api/profiles/abc/cdp"),
    );
    expect(screen.getByText("Copied")).toBeDefined();
    setApiBase("");
  });
});
```

Run: `pnpm vitest run src/components/CdpCopyButton.test.tsx` — Expected: FAIL (module missing).

Create `frontend/src/components/CdpCopyButton.tsx`:

```tsx
import { Check, Link } from "lucide-react";
import { useState } from "react";
import { getApiBase } from "../lib/api";

interface CdpCopyButtonProps {
  cdpUrl: string; // relative path like /api/profiles/<id>/cdp
}

export function CdpCopyButton({ cdpUrl }: CdpCopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const url = `${getApiBase() || window.location.origin}${cdpUrl}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // WebView clipboard-API fallback
      const ta = document.createElement("textarea");
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="btn-secondary flex items-center gap-1.5"
      title="Copy the CDP endpoint for Playwright/Puppeteer connect_over_cdp"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Link className="h-3.5 w-3.5" />}
      <span>{copied ? "Copied" : "Copy CDP URL"}</span>
    </button>
  );
}
```

- [ ] **Step 5: ProfileForm cleanup + CDP button**

In `frontend/src/components/ProfileForm.tsx`:
- Add `import { CdpCopyButton } from "./CdpCopyButton";`.
- Delete `clipboard_sync: true,` from the `useState` initializer and `clipboard_sync: profile.clipboard_sync,` from the `useEffect` mapping.
- Delete the whole clipboard-sync checkbox `<label>` block ("Enable clipboard sync by default in VNC viewer", lines 439-447).
- Change the auto-launch label text to `Launch automatically when the app starts`.
- In the header, after the Delete button inside the first `flex items-center gap-2` div, add:

```tsx
          {isEdit && profile?.status === "running" && profile.cdp_url && (
            <CdpCopyButton cdpUrl={profile.cdp_url} />
          )}
```

- [ ] **Step 6: Adapt remaining tests**

`frontend/src/lib/api.test.ts`:
- Delete the `api.setClipboard` and `api.getClipboard` describes.
- Replace the `api.launchProfile` test:

```ts
describe("api.launchProfile", () => {
  it("sends POST to launch endpoint", async () => {
    const result = { profile_id: "1", status: "running", cdp_url: "/api/profiles/1/cdp" };
    mockFetch.mockResolvedValueOnce(jsonResponse(result));
    const data = await api.launchProfile("1");
    expect(data.cdp_url).toBe("/api/profiles/1/cdp");
    expect(mockFetch.mock.calls[0][0]).toBe("/api/profiles/1/launch");
  });
});
```

`frontend/src/hooks/useProfiles.test.ts` — in `fakeProfile`, delete the `clipboard_sync: true,` and `vnc_ws_port: null,` lines and add `auto_launch: false, launch_args: [],` if missing (match the `Profile` type so `tsc` stays quiet).

- [ ] **Step 7: Full frontend gate**

Run: `pnpm test` then `pnpm build` (from `frontend/`)
Expected: PASS / compiles clean — `tsc -b` is the proof no deleted symbol is still referenced.

- [ ] **Step 8: Full-stack manual check**

Run: `pnpm tauri dev`
Expected: window opens → brief "Starting backend service..." → main profile UI (kernel already cached from earlier smokes). Create a profile, Launch — a real CloakBrowser window opens on the desktop; the form header shows "Copy CDP URL"; Stop closes it.

- [ ] **Step 9: Commit**

```bash
git add -A frontend
git commit -m "feat(frontend)!: desktop cutover — bootstrap gate, drop VNC viewer/login, CDP copy button"
```

---

## Milestone 5 — Cleanup & docs

### Task 16: Remove Docker, rewrite README and CLAUDE.md

**Files:**
- Delete: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `implementation_plan.md`
- Modify: `README.md` (rewrite), `CLAUDE.md` (rewrite)

- [ ] **Step 1: Delete the legacy deployment files**

```bash
git rm Dockerfile docker-compose.yml entrypoint.sh implementation_plan.md
```

(`implementation_plan.md` is superseded by `docs/superpowers/specs/2026-07-13-tauri-sidecar-design.md` — the spec says so explicitly.)

- [ ] **Step 2: Rewrite README.md**

Replace `README.md` in full:

```markdown
# CloakBrowser Manager

Desktop manager for CloakBrowser — a stealth, anti-fingerprint Chromium build. Each profile is an isolated browser identity (own fingerprint seed, proxy, timezone, locale, user agent) whose session data persists across restarts. Browsers open as real windows on your desktop.

## How it works

Tauri (Rust) shell + React UI + Python FastAPI sidecar:

- The shell spawns the backend (PyInstaller-frozen `server.exe`) on `127.0.0.1:8000` (configurable via a dialog on port conflict) and supervises it.
- The backend drives CloakBrowser through Playwright persistent contexts and exposes a per-profile CDP reverse proxy for automation.
- On first run the Chromium kernel is downloaded into the app data dir — it is never bundled (see `BINARY-LICENSE.md`).

Closing the app shuts down the backend and every browser it launched, flushing session data first. If the shell is killed, the backend notices on its own (stdin watchdog) and cleans up; if the backend is killed, Playwright's driver reaps the browsers.

## Data locations

| What | Windows | macOS / Linux |
|---|---|---|
| Profiles DB + browser data | `%LOCALAPPDATA%\CloakBrowser` | `~/Library/Application Support/CloakBrowser` / `~/.local/share/CloakBrowser` |
| Chromium kernel cache | `<data dir>\chromium-cache` | same pattern |
| Shell config (port) | `%APPDATA%\com.cloakbrowser.manager\config.json` | Tauri app-config dir |

## Automation (CDP)

While a profile is running, click **Copy CDP URL** in its form, then:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(
        "http://127.0.0.1:8000/api/profiles/<profile-id>/cdp"
    )
```

The proxied URL stays stable across relaunches even though the internal Chromium debug port rotates.

## Development

Prerequisites: Python ≥ 3.12, Node 20+ with pnpm, Rust toolchain (MSVC on Windows).

```bash
# Backend (one-time)
python -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Frontend (one-time)
cd frontend && pnpm install
```

Three workflows, fastest first:

1. **Pure web** — UI/API iteration without the shell:
   `backend/.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000` (repo root) + `pnpm dev` (in `frontend/`; Vite proxies `/api`). The bootstrap layer detects the missing Tauri bridge and skips shell integration.
2. **`pnpm tauri dev`** — full shell; spawns the backend from source (venv python). Requires a one-time `backend/.venv/Scripts/python.exe backend/build.py` so the declared sidecar binary exists.
3. **`pnpm tauri build`** — run `backend/build.py` first; produces the NSIS installer with the frozen sidecar.

Tests:

```bash
backend/.venv/Scripts/python.exe -m pytest -q                     # backend (repo root)
pnpm test                                                          # frontend (in frontend/)
cargo test --manifest-path frontend/src-tauri/Cargo.toml          # shell
```

## License

Manager code: see `LICENSE`. The CloakBrowser Chromium binary is licensed separately (`BINARY-LICENSE.md`) and must not be redistributed — it downloads at first run.
```

- [ ] **Step 3: Rewrite CLAUDE.md**

Replace `CLAUDE.md` in full (keep the Issue Tracking and Landing the Plane sections verbatim from the current file):

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

CloakBrowser Manager: a cross-platform desktop app (Tauri) managing profiles for CloakBrowser, a stealth anti-fingerprint Chromium build. Each profile is an isolated browser identity — own fingerprint seed, proxy, timezone, locale, user agent — with session data that persists across restarts. Launched browsers are real windows on the user's desktop.

Process model: Tauri (Rust) shell → spawns the FastAPI backend as a sidecar (`127.0.0.1:{port}`, default 8000) → backend drives CloakBrowser Chromium via Playwright persistent contexts. In release the backend is a PyInstaller onefile binary under `frontend/src-tauri/bin/` (target-triple named); in `tauri dev` it runs from source via the venv python. Design history: `docs/superpowers/specs/2026-07-13-tauri-sidecar-design.md`.

## Commands

### Backend (Python ≥3.12, venv at `backend/.venv`)

```bash
# One-time setup, from repo root
python -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# All tests, from repo root (pyproject.toml: testpaths=backend/tests, asyncio_mode=auto)
backend/.venv/Scripts/python.exe -m pytest -q

# Single file / single test
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -q
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k "launch" -q

# Dev server — run from repo root as a package (main.py uses relative imports)
backend/.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000

# Sidecar mode (what Tauri runs): argparse entry + stdin watchdog
backend/.venv/Scripts/python.exe -m backend.main --port 8000 [--data-dir X] [--allow-origin O]

# Freeze the sidecar for Tauri (installs to frontend/src-tauri/bin/)
backend/.venv/Scripts/python.exe backend/build.py
```

`conftest.py` injects a mock `cloakbrowser` module before backend imports, so the suite never downloads the real kernel and runs anywhere.

### Frontend (React 19 + TypeScript + Vite + pnpm, in `frontend/`)

```bash
pnpm install
pnpm dev                              # Vite on :5173, proxies /api → localhost:8000
pnpm test                             # vitest run (jsdom)
pnpm vitest run src/lib/api.test.ts   # single test file
pnpm build                            # tsc -b && vite build — also the type check; no linter
pnpm tauri dev                        # full desktop shell (backend from source)
pnpm tauri build                      # installer; run backend/build.py first
```

### Rust shell (`frontend/src-tauri/`)

```bash
cargo test --manifest-path frontend/src-tauri/Cargo.toml
```

## Architecture

**Lifecycle** — Rust reads the saved port from the Tauri app-config dir (default 8000), bind-probes it (`port-conflict` event + PortConfigModal on conflict), spawns the sidecar with `--port`, polls `GET /api/health` until 200 (30s timeout), then emits `backend-ready`. The frontend bootstrap layer (`frontend/src/bootstrap/`) mirrors this as a state machine and also polls health until `binary.state == "ready"` (first-run kernel download shows a waiting screen). Outside Tauri (`pnpm dev`) bootstrap short-circuits and uses relative API paths.

**Shutdown (three layers)** — (1) window close → Rust `RunEvent::ExitRequested` → `POST /api/shutdown` → uvicorn `should_exit` → lifespan `cleanup_all()` closes every Playwright context (session data flushes) → Rust waits ≤10s then kills. (2) Shell killed → backend's stdin watchdog sees EOF → same graceful path. (3) Backend killed → Playwright's node driver reaps its Chromium children.

**Launch flow** — `POST /api/profiles/{id}/launch` → `BrowserManager.launch` (`backend/browser_manager.py`): rejects with 503 until `binary_status.tracker` is ready; allocates a rotating CDP port (TIME_WAIT avoidance); cleans stale `Singleton*` locks; builds fingerprint/proxy/humanize args from the profile row; `launch_persistent_context_async` headed with **no viewport override** (cloakbrowser's no_viewport keeps outerWidth/innerWidth consistent). `context.on("close")` reaps state when the user closes the window; profiles with `auto_launch` start once the kernel is ready.

**CDP path** — `/api/profiles/{id}/cdp` (+ `/cdp/json/version`, `/cdp/json/list`, WS `/cdp/devtools/...`) reverse-proxies Chromium DevTools and rewrites `webSocketDebuggerUrl` so external Playwright/Puppeteer connect through the stable manager port.

**Security** — no auth; backend binds `127.0.0.1` only. `OriginCheckMiddleware` 403s state-changing requests and WebSocket upgrades whose `Origin` isn't whitelisted (Tauri WebView origins + Vite dev; extend via `--allow-origin`); no-Origin clients (curl, Playwright, the Rust shell) pass. CORS uses the same list.

**Persistence** — `backend/database.py`: raw sqlite3 (WAL); data dir from `--data-dir` or `platformdirs.user_data_dir("CloakBrowser")` (lazy default), profiles + tags tables, per-profile Chromium user-data dirs under `<data>/profiles/<id>`. Kernel cache is pinned inside the data dir via `CLOAKBROWSER_CACHE_DIR`.

## Hard Constraints

- **Never bundle the CloakBrowser Chromium binary** into any distributed artifact (PyInstaller sidecar / Tauri installer) — `BINARY-LICENSE.md` forbids redistribution. It must download on first run via `cloakbrowser.download.ensure_binary()`.
- Conventional Commits (`feat:`, `fix:`, `chore:`, optional scope); one commit per logical task.
- `backend/main.py` uses relative imports — always run as a package from repo root.
```

Then append the current CLAUDE.md's `## Issue Tracking` and `## Landing the Plane (Session Completion)` sections unchanged.

- [ ] **Step 4: Verify nothing references the deleted files**

Run: `grep -rn "docker\|entrypoint.sh\|implementation_plan" --include="*.md" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.json" . | grep -v node_modules | grep -v src-tauri/target | grep -v docs/superpowers`
Expected: no hits outside historical docs. Run the three test suites once more (backend pytest, pnpm test, cargo test) — all green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore!: remove Docker deployment, rewrite docs for the desktop client"
```

---

## Milestone 6 — End-to-end verification

### Task 17: Manual verification checklist (design doc §14)

No new code — this task proves the whole system. Fix-and-recheck anything that fails (fixes are their own `fix:` commits).

- [ ] **1. Independent builds without Docker**

```bash
backend/.venv/Scripts/python.exe backend/build.py        # → frontend/src-tauri/bin/server-*.exe
cd frontend && pnpm build                                 # → frontend/dist
```

- [ ] **2. Packaged app starts end-to-end**

```bash
cd frontend && pnpm tauri build
```

Install/run the NSIS output (`frontend/src-tauri/target/release/bundle/nsis/*.exe` — or run `frontend/src-tauri/target/release/cloakbrowser-manager.exe` directly). The window must reach the main profile UI. Watch the WebView devtools console for CORS/Origin 403s — if the real WebView2 origin differs from `http://tauri.localhost`, fix `DEFAULT_ALLOWED_ORIGINS` in `backend/main.py` (design doc §16 flagged this as the one thing to calibrate on real hardware).

- [ ] **3. First-run kernel download**

```bash
rm -rf "$LOCALAPPDATA/CloakBrowser/chromium-cache"
```

Relaunch the packaged app: it must show "Downloading browser core..." and flip to the main UI when done — kernel files land under `%LOCALAPPDATA%\CloakBrowser\chromium-cache`, not in a `_MEI*` temp dir.

- [ ] **4. Port conflict flow**

Occupy 8000 (`python -c "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',8000)); s.listen(); time.sleep(600)"`), launch the app → PortConfigModal appears; enter 8001 → app starts normally; `%APPDATA%\com.cloakbrowser.manager\config.json` now says 8001. Free the port and confirm next launch still uses 8001.

- [ ] **5. Profile launch on the real desktop**

Create a profile (with a proxy if available), Launch → a native CloakBrowser window opens. Open the bookmarked detection sites (Rebrowser Bot Detector, Pixelscan) and confirm fingerprint/proxy hold up. Close the browser window by hand → the profile flips to "stopped" in the UI within ~3s (poller).

- [ ] **6. External CDP automation**

Copy the CDP URL from the running profile's form, then from any Python env with playwright:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("<copied url>")
    print(b.contexts[0].pages)
```

Expected: connects and lists the open pages.

- [ ] **7. Three-layer teardown**

- Close the app window normally → `tasklist` shows no `server`/`chrome` leftovers within ~10s.
- Relaunch; kill the Tauri process via Task Manager → sidecar exits by itself (stdin watchdog), Chromium follows.
- Relaunch; kill the sidecar `server.exe` via Task Manager → the UI shows BackendErrorScreen; Retry restores a working app.

- [ ] **8. Land the branch**

Update/close tracked issues in the committed markdown doc, then:

```bash
git pull --rebase && git push
git status   # must be "up to date with origin"
```

---

## Design-doc deviations (deliberate, agreed rationale)

1. **Rust does not pass `--data-dir`** (§4.1 showed it; §6.1 defines platformdirs as the backend default). Passing both would create two sources of truth — Tauri's `app_data_dir` is `%APPDATA%\com.cloakbrowser.manager` while §6.1 specifies `%LOCALAPPDATA%\CloakBrowser`. The backend's platformdirs default wins; `--data-dir` remains a dev/test/portable escape hatch.
2. **Port probe binds instead of connecting** (§4.1 said "TCP 连接尝试"). The backend must *bind* the port; bind-probing also catches TIME_WAIT and bound-but-not-listening states a connect probe misses.
3. **Added `get_backend_state` command + `backend-starting` event** (not in §9's list). The sidecar spawn begins before the WebView attaches listeners; without a pull-based snapshot the frontend can miss `port-conflict`/`backend-ready` forever.
4. **`cloakbrowser[geoip]>=0.4.10`** (was `>=0.3.31`). §13's integration facts (`ensure_binary`, `CLOAKBROWSER_CACHE_DIR`, headed no-viewport gating) were verified against 0.4.10; older versions may lack them.
5. **`LoginRequest`/`ClipboardRequest` deletion is deferred** to the tasks that stop importing them (Tasks 4/5), keeping every intermediate commit green.
6. **The `clipboard_sync` DB column survives** in `backend/database.py` although models/API no longer expose it — dropping it would be a destructive migration for existing profile DBs; sqlite ignores the extra column and new writes default it. Removal can ride any future schema migration.

