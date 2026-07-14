# Follow-ups — Tauri desktop client branch

Source: per-task and
final whole-branch code reviews of `feature/tauri-desktop-client` (2026-07-13). None are
merge-blocking; the final review approved the branch with these as follow-up work.

## Remaining manual verification (plan Task 17, needs a human at the GUI)

- [x] Run the packaged app (`frontend/src-tauri/target/release/cloakbrowser-manager.exe` or the
      NSIS installer under `target/release/bundle/nsis/`) and confirm it reaches the main profile
      UI. **Watch the WebView devtools console for CORS/Origin 403s** — if the real WebView2
      origin differs from `http://tauri.localhost`, fix `DEFAULT_ALLOWED_ORIGINS` in
      `backend/main.py`. This is the highest-risk untested item (a mismatch makes the app
      appear read-only).
- [x] First-run kernel UX (superseded by kernel management, 2026-07-13): with an empty kernel
      library the app must open to the main UI with the amber "No browser kernel configured"
      banner; Settings → Import registers an existing kernel dir; Download recommended fetches
      and registers the recommended version.
- [ ] Port-conflict flow: occupy 8000, launch → PortConfigModal; choose 8001; config.json persists it.
- [x] Real profile launch + fingerprint sites (Rebrowser Bot Detector, Pixelscan); manual window
      close flips profile to "stopped" within ~3s.
- [x] External CDP: `connect_over_cdp` with the copied URL lists open pages.
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
- [x] Backend tests: convert direct `main.browser_mgr.launch = AsyncMock(...)` reassignments to
      `monkeypatch.setattr` (mock currently leaks onto the singleton). — Done in the kernel
      management work (Task 4, commit d5a6672).
- [ ] `useBootstrap`: add a disposed guard inside the health-poll `tick` (benign setState after
      unmount today).
- [ ] `CdpCopyButton`: test the `document.execCommand("copy")` fallback branch (the WebView path).
- [ ] Optional defense-in-depth: Host-header allowlist in `OriginCheckMiddleware` against DNS
      rebinding reads (CORS already covers the browser-read case).

---

# Follow-ups — kernel management (2026-07-13, plan `2026-07-13-kernel-management.md`)

Source: per-task reviews + final whole-branch review of a3d3ff3..1156109. The final review
approved the branch ("Ready to merge: Yes"); findings #2 (nullable `binary_version` type) and
#3 (`run_download` stuck-tracker) were fixed pre-merge (1156109, 8c000af). Everything below is
non-blocking.

## Accepted scope decision (release-notes item, not a bug)

- [x] **Upgrade from the pre-kernel-library branch boots to an empty library.** The design spec
      explicitly scoped out migration ("no existing users"). A machine that ran the previous
      branch has a valid kernel at `<data>/chromium-cache/chromium-{version}/` but no `kernels`
      row → amber banner, no auto-launch, launch 503s. ~~Do NOT import the cache directory
      itself~~ — **fixed 2026-07-14** (hit live on the dev machine as an opaque "Failed to
      fetch"): importing the cache directory now adopts it in place as a `downloaded` kernel;
      importing *another* copy of a version whose cache slot is occupied by a real directory
      returns a clear 400 instead of an unhandled 500. `Download recommended` remains the other
      recovery path. A startup scan auto-registering `chromium-*` dirs is still an option if
      this ever matters beyond dev machines.

## Manual GUI verification (needs a human; API paths already smoke-tested live)

- [x] `pnpm tauri dev`: empty library → amber banner → Open Settings; import a **real** kernel
      directory (native folder picker); banner disappears; profile launches with it
      (`browser_version=` pin — also confirms the real `launch_persistent_context_async`
      accepts the kwarg); deleting that kernel while the profile runs is refused (409 surfaced
      in the UI); kernel dropdown in the profile form lists it.

## Code hardening (all Minor, from reviews)

- [ ] `kernels_api._kernel_in_use`: also consider profiles mid-launch (in `_launching`, before
      `running` insertion) — TOCTOU lets DELETE remove kernel files during the Playwright await;
      today it fails the launch cleanly (500) instead of refusing (409).
- [x] `kernel_manager`: use `os.path.lexists()` in `create_link`/`remove_kernel_files` guards —
      dangling NTFS junctions (target deleted) evade `exists() or is_symlink()`, making
      re-import error opaquely and leaking dead junctions. — Done 2026-07-14 with the
      import-cache-dir fix; unhandled 500s now also carry CORS headers (readable in the
      WebView instead of "Failed to fetch"), and the import endpoint maps `OSError` to a
      readable 500.
- [ ] Sidecar shutdown cosmetics (found verifying the import fix live): after a graceful
      `POST /api/shutdown` with stdin still open, the stdin-watchdog daemon thread blocked in
      `sys.stdin.buffer.read()` trips `Fatal Python error: _enter_buffered_busy` at interpreter
      finalization (cleanup has already completed; exit code is nonzero and the message lands
      in the sidecar log). Fix idea: `os.read(sys.stdin.fileno(), ...)` in the watchdog instead
      of the buffered reader, or `os._exit`-style teardown after cleanup.
- [ ] `kernel_manager.remove_kernel_files`: `shutil.rmtree(..., ignore_errors=True)` masks
      partial deletes (read-only files) — surface failures.
- [ ] `browser_manager.auto_launch_all`: gate is coarser than resolution — a profile with an
      explicit valid `kernel_id` does not auto-launch when no *default* kernel is set. Rare
      state; add a comment or narrow the gate.
- [ ] Threat-model note: `kernel_manager._run_version_probe` executes `chrome.exe --version`
      from the user-selected import directory (only when the dir name doesn't carry the
      version). Acceptable for a localhost single-user app; document it.
- [ ] `conftest.py`: drop the dead `CHROMIUM_VERSION` mock and its stale comment.
- [x] `frontend/tsconfig.tsbuildinfo` is tracked — `git rm --cached` + `.gitignore` entry
      (every `pnpm build` dirties the tree). — Done 2026-07-14.
- [ ] Vitest: register jest-dom once via `setupFiles` instead of per-file imports
      (SettingsPage.test.tsx / ProfileForm.test.tsx pattern).

## Test-coverage gaps (all Minor)

- [ ] `database`: from-old-schema `init_db()` migration test (profiles table without
      `kernel_id` → ALTER branch actually exercised).
- [ ] `binary_status`: `run_download` version-None branch; `start()` success path; move
      `TestDownloadRunner` singleton resets into `finally`/fixture (new registration-failure
      test already does this).
- [ ] `test_browser_manager.TestKernelResolution`: restore the module-level launch mock's
      `return_value` via monkeypatch (currently mutated without teardown).
- [ ] `test_kernels_api`: drop unused `import pytest`; cover the explicit-`kernel_id` 409
      delete branch; API-level 409-body assertion for `KernelInvalidError`.
- [ ] Frontend: direct unit tests for `api.downloadKernel`/`downloadStatus`; `useKernels`
      unmount-cleanup / poll-error / single-interval paths; SettingsPage confirm-false branch +
      error/download-error banners; useBootstrap transient-poll-failure and
      polling-stops-after-ready assertions.
- [ ] `useKernels` mount `refresh()` + `useBootstrap` `tick`: optional disposed guards
      (benign setState-after-unmount under React 19).
