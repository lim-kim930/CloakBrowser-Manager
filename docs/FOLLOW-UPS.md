# Follow-ups — Tauri desktop client branch

Tracked here because the `bd` CLI is not installed on this machine. Source: per-task and
final whole-branch code reviews of `feature/tauri-desktop-client` (2026-07-13). None are
merge-blocking; the final review approved the branch with these as follow-up work.

## Remaining manual verification (plan Task 17, needs a human at the GUI)

- [ ] Run the packaged app (`frontend/src-tauri/target/release/cloakbrowser-manager.exe` or the
      NSIS installer under `target/release/bundle/nsis/`) and confirm it reaches the main profile
      UI. **Watch the WebView devtools console for CORS/Origin 403s** — if the real WebView2
      origin differs from `http://tauri.localhost`, fix `DEFAULT_ALLOWED_ORIGINS` in
      `backend/main.py`. This is the highest-risk untested item (a mismatch makes the app
      appear read-only).
- [ ] First-run kernel download: remove `%LOCALAPPDATA%\CloakBrowser\chromium-cache`, relaunch,
      confirm "Downloading browser core..." → main UI, cache lands in the data dir.
- [ ] Port-conflict flow: occupy 8000, launch → PortConfigModal; choose 8001; config.json persists it.
- [ ] Real profile launch + fingerprint sites (Rebrowser Bot Detector, Pixelscan); manual window
      close flips profile to "stopped" within ~3s.
- [ ] External CDP: `connect_over_cdp` with the copied URL lists open pages.
- [ ] Three-layer teardown: window close (graceful `RunEvent::ExitRequested` path — not yet
      exercised), Task-Manager kill of the shell (stdin watchdog — already verified live in
      Task 13), kill of the sidecar (BackendErrorScreen + Retry).

## Code hardening (from reviews, all Minor)

- [ ] `browser_manager.launch()`: register `context.on("close")` **after** inserting into
      `self.running` — closes a narrow race where a browser dying instantly leaves a stale entry.
- [ ] `lib.rs`: per-generation `child_exited` flag (capture a fresh `Arc<AtomicBool>` per
      `spawn_backend` in the Terminated closure) — closes the restart-during-startup race where
      an old health-poll thread can clobber the new snapshot with "error".
- [ ] `lib.rs`: move the blocking shutdown wait into `spawn_blocking`; consider non-panicking
      lock handling.
- [ ] `ureq` in `Cargo.toml`: `default-features = false` (HTTP-only, localhost) to trim the binary.
- [ ] Backend tests: convert direct `main.browser_mgr.launch = AsyncMock(...)` reassignments to
      `monkeypatch.setattr` (mock currently leaks onto the singleton).
- [ ] `useBootstrap`: add a disposed guard inside the health-poll `tick` (benign setState after
      unmount today).
- [ ] `CdpCopyButton`: test the `document.execCommand("copy")` fallback branch (the WebView path).
- [ ] Optional defense-in-depth: Host-header allowlist in `OriginCheckMiddleware` against DNS
      rebinding reads (CORS already covers the browser-read case).
