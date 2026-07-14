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

**Lifecycle** — Rust reads the saved port from the Tauri app-config dir (default 8000), bind-probes it (`port-conflict` event + PortConfigModal on conflict), spawns the sidecar with `--port`, polls `GET /api/health` until 200 (30s timeout), then emits `backend-ready`. The frontend bootstrap layer (`frontend/src/bootstrap/`) mirrors this as a state machine and polls health for backend liveness only — kernel state no longer gates startup. With an empty kernel library the app opens with an amber banner pointing to Settings, where the user imports an existing kernel directory or downloads the recommended version on demand. Outside Tauri (`pnpm dev`) bootstrap short-circuits and uses relative API paths.

**Shutdown (three layers)** — (1) window close → Rust `RunEvent::ExitRequested` → `POST /api/shutdown` → uvicorn `should_exit` → lifespan `cleanup_all()` closes every Playwright context (session data flushes) → Rust waits ≤10s then kills. (2) Shell killed → backend's stdin watchdog sees EOF → same graceful path. (3) Backend killed → Playwright's node driver reaps its Chromium children.

**Launch flow** — `POST /api/profiles/{id}/launch` → `BrowserManager.launch` (`backend/browser_manager.py`): resolves the profile's kernel (its `kernel_id`, else the library default) from the `kernels` table — 503 `no_kernel` if none configured, 409 if the kernel's files are missing on disk; never silently falls back to a different kernel. Allocates a rotating CDP port (TIME_WAIT avoidance); cleans stale `Singleton*` locks; builds fingerprint/proxy/humanize args from the profile row; `launch_persistent_context_async` headed with `browser_version=` pinning the resolved kernel and **no viewport override** (cloakbrowser's no_viewport keeps outerWidth/innerWidth consistent). `context.on("close")` reaps state when the user closes the window; profiles with `auto_launch` start at backend startup when a default kernel exists.

**CDP path** — `/api/profiles/{id}/cdp` (+ `/cdp/json/version`, `/cdp/json/list`, WS `/cdp/devtools/...`) reverse-proxies Chromium DevTools and rewrites `webSocketDebuggerUrl` so external Playwright/Puppeteer connect through the stable manager port.

**Security** — no auth; backend binds `127.0.0.1` only. `OriginCheckMiddleware` 403s state-changing requests and WebSocket upgrades whose `Origin` isn't whitelisted (Tauri WebView origins + Vite dev; extend via `--allow-origin`); no-Origin clients (curl, Playwright, the Rust shell) pass. CORS uses the same list.

**Persistence** — `backend/database.py`: raw sqlite3 (WAL); data dir from `--data-dir` or `platformdirs.user_data_dir("CloakBrowser")` (lazy default), profiles + tags + kernels tables, per-profile Chromium user-data dirs under `<data>/profiles/<id>`. Kernel cache is pinned inside the data dir via `CLOAKBROWSER_CACHE_DIR`; imported kernels stay at the user's original path, referenced by an NTFS junction/symlink `<cache>/chromium-{version}` (`backend/kernel_manager.py`) — never copied, and deleting an imported kernel never touches the original directory.

## Hard Constraints

- **Never bundle the CloakBrowser Chromium binary** into any distributed artifact (PyInstaller sidecar / Tauri installer) — `BINARY-LICENSE.md` forbids redistribution. Kernels enter the library at runtime only: the user imports an existing directory (linked in place, never copied) or triggers an on-demand download via `cloakbrowser.download.ensure_binary()`.
- Conventional Commits (`feat:`, `fix:`, `chore:`, optional scope); one commit per logical task.
- `backend/main.py` uses relative imports — always run as a package from repo root.

## Issue Tracking

This project uses **bd** (beads). Run `bd onboard` to get started.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

If the `bd` CLI is not installed on the machine, track follow-ups in a committed markdown doc instead and skip `bd sync`.

## Landing the Plane (Session Completion)

When ending a work session, work is NOT complete until `git push` succeeds:

1. File issues for remaining work
2. Run quality gates if code changed (tests, builds)
3. Update issue status (close finished, update in-progress)
4. Push: `git pull --rebase`, `bd sync` (if bd available), `git push`, then `git status` must show "up to date with origin"
5. Clean up stashes and stale branches, then hand off context for the next session

Never stop before pushing and never say "ready to push when you are" — push it yourself. **Exception — interactive auth:** if push needs credentials only a human can provide (e.g. a Git Credential Manager GUI prompt in a non-interactive session), stop retrying: verify everything is committed, hand the exact push command to the user, and say why.
