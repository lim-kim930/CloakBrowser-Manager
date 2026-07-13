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
