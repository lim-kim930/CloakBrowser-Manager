# Agent Instructions

CloakBrowser-Manager: a browser-profile manager for CloakBrowser (anti-fingerprint browser).
Two runtime modes share one codebase — do not break either:

- **VNC mode** (Docker): each profile renders in a virtual display, streamed to the web UI via KasmVNC/noVNC. The original deployment target; behavior must stay unchanged.
- **Native mode** (Windows desktop): browser windows open directly on the desktop; a pywebview shell (`desktop/`) hosts the same web UI and is packaged with PyInstaller.

The single mode switch is `use_vnc()` in `backend/config.py` (`USE_VNC` env wins; otherwise auto-detect Xvnc on PATH). Never branch on OS. Explicit env vars (`USE_VNC`, `DATA_DIR`, `CLOAK_PORT`) always win over defaults.

## Layout

- `backend/` — FastAPI + uvicorn (Python ≥3.12, venv at `backend/.venv`). Tests in `backend/tests`.
- `frontend/` — React 19 + TypeScript + Vite + Tailwind. Tests: vitest.
- `desktop/` — Windows client shell: settings, uvicorn thread, close-behavior controller, tray, `app.py` entry, PyInstaller spec. Deps isolated in `desktop/requirements.txt` (never add them to `backend/requirements.txt`). Tests in `desktop/tests`.
- `docs/superpowers/plans/` — design specs, implementation plans, follow-up trackers.

## Commands

```bash
# Backend + desktop tests (from repo root; pytest collects backend/tests + desktop/tests)
backend/.venv/Scripts/python.exe -m pytest -q

# Frontend (from frontend/; package manager of record is npm — package-lock.json, Dockerfile.
# pnpm works as a local runner; its artifacts are gitignored)
npm test        # = vitest run (non-watch)
npm run build   # = tsc -b && vite build

# Run desktop client from source (needs frontend/dist: build frontend first)
backend/.venv/Scripts/python.exe -m desktop.app

# Package Windows client (see desktop/build.md)
backend/.venv/Scripts/pyinstaller.exe desktop/CloakBrowserManager.spec

# Docker / VNC mode
docker compose up --build   # then http://localhost:8080
```

## Hard Constraints

- **Never bundle the CloakBrowser kernel** (binary license forbids redistribution). It downloads on first run via `BinaryManager` / `cloakbrowser.download.ensure_binary()`.
- **VNC mode is frozen surface**: changes must be additive or native-gated; zero VNC code deletion.
- Conventional Commits; one commit per logical task.

## Issue Tracking

This project uses **bd** (beads). Run `bd onboard` to get started.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

If the `bd` CLI is not installed on the machine, track follow-ups as a committed markdown doc under `docs/superpowers/plans/` instead (precedent: `native-desktop-followups.md`) and skip `bd sync`.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
- **Exception — interactive auth:** if push requires credentials only a human can provide (e.g. Git Credential Manager GUI prompt in a non-interactive session), stop retrying: verify everything is committed, then hand the exact push command to the user and say why. Do not leave push attempts hanging.
