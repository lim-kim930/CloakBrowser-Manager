# Kernel Management Design

Date: 2026-07-13
Status: Approved (brainstorming)

## Problem

The backend currently auto-downloads the CloakBrowser Chromium kernel on every startup (`start_background_ensure()` → `ensure_binary()`), tracks a single kernel via the `binary_status.tracker` singleton, and offers no user control. Users must be able to manage kernels themselves: import kernels they downloaded elsewhere, keep several versions, pick which one each profile uses, and optionally download through the app. No auto-download.

There are no existing users, so no migration of previously downloaded caches is needed.

## Decisions (from brainstorming)

- **Per-profile kernel selection**, with a global **default kernel** that profiles use unless they explicitly pick one.
- Imported kernels are **referenced at their original path**, not copied.
- Import unit is a **kernel directory** (the extracted folder containing the executable).
- **Fully manual first run**: no auto-download; empty kernel library guides the user to the settings page.
- In-app download offers **only the recommended version** (the cloakbrowser platform default).
- If a profile's bound kernel is missing at launch, **fail with an error** (never silently fall back to another kernel — a kernel swap changes the fingerprint environment).

## Chosen Approach: link-into-cache + version pin

`launch_persistent_context_async` does not accept an executable path; it internally calls `ensure_binary(browser_version=...)`, which returns `<cache>/chromium-{version}/<exe>` without touching the network whenever that path exists. So:

- Imported kernel directories are exposed to cloakbrowser by creating a **link** named `chromium-{version}` inside `<data>/chromium-cache/` pointing at the user's original directory — an NTFS **junction** on Windows (no admin rights needed; created via `_winapi.CreateJunction`), a symlink on macOS/Linux.
- Launch passes the profile's kernel version as `browser_version=`, so downloaded and imported kernels share one code path, and concurrent launches of different kernels need no global state.

Rejected alternatives: `CLOAKBROWSER_BINARY_PATH` env override (process-global, forces serializing launches), and bypassing cloakbrowser's launch to call Playwright directly (would re-implement all stealth argument building; fragile).

## Data Model (`backend/database.py`)

New `kernels` table:

| column | notes |
|---|---|
| `id` | uuid |
| `version` | e.g. `146.0.7680.177.5`; unique |
| `source` | `imported` \| `downloaded` |
| `source_path` | user's original directory for `imported`; NULL for `downloaded` |
| `is_default` | exactly one row at most |
| `created_at` | |

`profiles` gains a nullable `kernel_id` column (FK to `kernels`; NULL = follow the default kernel).

## Backend API

- `GET /api/kernels` — list; each entry includes validity (executable exists), `is_default`, and referencing-profile count.
- `POST /api/kernels/import` — body: directory path (picked via Tauri native folder dialog).
  1. Verify the platform executable exists in the directory (`chrome.exe` on Windows, `chrome` on Linux, `Chromium.app/...` on macOS).
  2. Detect version: directory name matching `chromium-{version}`; else run the executable with `--version`; if both fail, reject with an error asking the user to check the directory.
  3. Create the `chromium-{version}` junction/symlink in the cache dir. Same version already registered → reject as "already imported".
  4. Insert into `kernels`; the first kernel ever registered becomes the default automatically.
- `POST /api/kernels/download` — background thread runs `ensure_binary()` (unpinned recommended version); progress via a reworked tracker; on success record `source=downloaded` with the version derived from the returned executable path's `chromium-{version}` directory name. Only one download at a time.
  Note on versions: the string stored in `kernels.version` only needs to round-trip — it names the link/cache directory and is what launch pins via `browser_version=`. It does not have to match cloakbrowser's official 5-part scheme (a 4-part `--version` result from an imported kernel works, since `ensure_binary` resolves a pinned version by checking `chromium-{version}` existence before any network call).
- `GET /api/kernels/download/status` — poll download progress/state.
- `PUT /api/kernels/{id}/default` — set default.
- `DELETE /api/kernels/{id}` — `imported`: remove link + row only, never touch the user's directory; `downloaded`: delete the cache directory too. Refuse if any running profile is using it. Deleting the default reassigns default to another kernel if one exists.

## Startup & Launch Changes

- `main.py` lifespan no longer calls `start_background_ensure()`.
- `binary_status` semantics change from "the kernel's download state" to "kernel library state". `/api/health` `binary.state` becomes `"none" | "downloading" | "ready" | "error"`:
  - `none` — kernel library empty (fresh install)
  - `ready` — at least one usable kernel registered
  - `downloading` — a user-triggered download is in progress
  - `error` — the last download failed
  Initial state derived by reading the `kernels` table at startup.
- `browser_manager.launch`:
  1. Resolve `profile.kernel_id`, falling back to the default kernel. No kernel at all → 503, error code `no_kernel`.
  2. Validate the kernel's executable actually exists (junction target may have been deleted/moved) → 409 with a message naming the kernel and directing the user to the settings page. No automatic fallback.
  3. Call `launch_persistent_context_async(..., browser_version=kernel.version)`.
- `auto_launch`: if the kernel library is ready at startup, auto-launch profiles start immediately; if empty, they are skipped silently (user launches manually after configuring a kernel).

## Frontend

**Bootstrap** (`frontend/src/bootstrap/`):
- Remove the `downloading-binary` blocking screen. `binary.state === "none"` counts as ready for bootstrap: the app enters the main UI with a persistent banner "尚未配置浏览器内核" linking to settings.
- `downloading` no longer blocks the UI; progress lives in the settings page.
- `DownloadingScreen` remains only for "waiting for backend".

**Settings page (new)**:
- Simple page switch (profiles / settings) with a sidebar or header entry; settings currently holds one section, Kernel Management, extensible later.
- Kernel list rows: version, source (imported/downloaded), original path (imported), default badge, referencing-profile count, validity (invalid rows highlighted with a "remove" action).
- Actions: **Import** (Tauri folder dialog → import API; errors like "chrome.exe not found", "version detection failed", "already imported" surface as toasts), **Download recommended** (button → progress bar polling status → refresh list), **Set default**, **Delete** (confirm dialog; blocked-while-running message).

**Profile form**: a "kernel version" dropdown listing the library plus a default option "跟随默认内核 (当前: {version})". Profile list/detail shows the kernel in use. Launch errors from an invalid kernel toast with guidance to the settings page.

## Testing

- Backend pytest: kernels API CRUD, import validation (missing exe, version detection paths, duplicate version), junction creation against `tmp_path`, launch resolution (explicit kernel / default / none / invalid), health-state transitions. `conftest.py` already mocks `cloakbrowser`.
- Frontend vitest: bootstrap handling of the new `binary.state` values, settings-page components, profile-form kernel dropdown.
- Rust shell: no changes.
