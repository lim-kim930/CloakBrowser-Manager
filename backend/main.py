"""CloakBrowser Manager — FastAPI backend.

REST API + CDP reverse proxy for the CloakBrowser desktop client.
Runs as a Tauri sidecar (PyInstaller-frozen) or from source for development.
Browsers launch as real windows on the user's desktop; there is no VNC layer.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import binary_status, database as db
from .browser_manager import BrowserManager, KernelInvalidError, KernelNotConfiguredError
from .kernels_api import router as kernels_router
from .models import (
    BinaryStatus,
    HealthResponse,
    LaunchResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileStatusResponse,
    ProfileUpdate,
    StatusResponse,
    TagResponse,
)

logger = logging.getLogger("cloakbrowser.manager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


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


# Singleton browser manager
browser_mgr = BrowserManager()


MANAGER_VERSION = "0.1.0"

# Set by main() so /api/shutdown and the stdin watchdog can stop the server.
_uvicorn_server: uvicorn.Server | None = None


def request_shutdown() -> None:
    """Ask the running uvicorn server to exit gracefully (lifespan cleanup runs)."""
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
    else:
        logger.warning("Shutdown requested but no uvicorn server reference (dev mode)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    browser_mgr._auto_launch_task = asyncio.create_task(browser_mgr.auto_launch_all())
    logger.info("CloakBrowser Manager started")
    yield
    logger.info("Shutting down — stopping all browsers...")
    if browser_mgr._auto_launch_task and not browser_mgr._auto_launch_task.done():
        browser_mgr._auto_launch_task.cancel()
        await asyncio.gather(browser_mgr._auto_launch_task, return_exceptions=True)
    await browser_mgr.cleanup_all()


app = FastAPI(title="CloakBrowser Manager", lifespan=lifespan)

# CORS added last = outermost, so it answers preflights before the origin
# check sees them (OPTIONS isn't a write method anyway).
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kernels_router)


async def _unhandled_error_response(request: Request, exc: Exception) -> JSONResponse:
    """JSON 500 that carries CORS headers for allowed origins.

    Unhandled exceptions are answered by Starlette's ServerErrorMiddleware,
    which sits OUTSIDE CORSMiddleware — its default plain 500 has no
    Access-Control-Allow-Origin, so the Tauri WebView blocks the response
    and fetch surfaces an opaque "Failed to fetch" instead of the error.
    """
    response = JSONResponse(
        {"detail": f"Internal server error: {exc}"}, status_code=500
    )
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


app.add_exception_handler(Exception, _unhandled_error_response)


# ── Profile CRUD ──────────────────────────────────────────────────────────────


@app.get("/api/profiles", response_model=list[ProfileResponse])
async def list_profiles():
    profiles = db.list_profiles()
    result = []
    for p in profiles:
        status = browser_mgr.get_status(p["id"])
        p["status"] = status["status"]
        p["cdp_url"] = status["cdp_url"]
        p["tags"] = [TagResponse(**t) for t in p.get("tags", [])]
        result.append(ProfileResponse(**p))
    return result


@app.post("/api/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(req: ProfileCreate):
    data = req.model_dump()
    tags = data.pop("tags", None)
    if tags:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]
    else:
        data["tags"] = []
    profile = db.create_profile(**data)
    status = browser_mgr.get_status(profile["id"])
    profile["status"] = status["status"]
    profile["cdp_url"] = status["cdp_url"]
    profile["tags"] = [TagResponse(**t) for t in profile.get("tags", [])]
    return ProfileResponse(**profile)


@app.get("/api/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    status = browser_mgr.get_status(profile_id)
    profile["status"] = status["status"]
    profile["cdp_url"] = status["cdp_url"]
    profile["tags"] = [TagResponse(**t) for t in profile.get("tags", [])]
    return ProfileResponse(**profile)


@app.put("/api/profiles/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: str, req: ProfileUpdate):
    # Only pass fields that were explicitly set
    data = req.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    if tags is not None:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]
    profile = db.update_profile(profile_id, **data)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    status = browser_mgr.get_status(profile_id)
    profile["status"] = status["status"]
    profile["cdp_url"] = status["cdp_url"]
    profile["tags"] = [TagResponse(**t) for t in profile.get("tags", [])]
    return ProfileResponse(**profile)


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    # Stop browser if running
    if profile_id in browser_mgr.running:
        await browser_mgr.stop(profile_id)

    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    user_data_dir = Path(profile["user_data_dir"])

    # DB first — if this fails, filesystem is untouched
    db.delete_profile(profile_id)

    # Then clean up disk
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)

    return {"ok": True}


# ── Launch / Stop ─────────────────────────────────────────────────────────────


@app.post("/api/profiles/{profile_id}/launch", response_model=LaunchResponse)
async def launch_profile(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_id in browser_mgr.running:
        raise HTTPException(status_code=409, detail="Profile is already running")

    try:
        await browser_mgr.launch(profile)
    except KernelNotConfiguredError:
        raise HTTPException(status_code=503, detail="no_kernel")
    except KernelInvalidError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to launch profile %s: %s", profile_id, exc)
        raise HTTPException(status_code=500, detail="Failed to launch browser")

    return LaunchResponse(
        profile_id=profile_id,
        status="running",
        cdp_url=f"/api/profiles/{profile_id}/cdp",
    )


@app.post("/api/profiles/{profile_id}/stop")
async def stop_profile(profile_id: str):
    if profile_id not in browser_mgr.running:
        raise HTTPException(status_code=404, detail="Profile is not running")
    await browser_mgr.stop(profile_id)
    return {"ok": True}


@app.get("/api/profiles/{profile_id}/status", response_model=ProfileStatusResponse)
async def get_profile_status(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    status = browser_mgr.get_status(profile_id)
    return ProfileStatusResponse(**status)


# ── System Status ─────────────────────────────────────────────────────────────


@app.get("/api/status", response_model=StatusResponse)
async def get_system_status():
    profiles = db.list_profiles()
    default = db.get_default_kernel()
    return StatusResponse(
        running_count=len(browser_mgr.running),
        binary_version=default["version"] if default else None,
        profiles_total=len(profiles),
    )


# ── Health / Shutdown ─────────────────────────────────────────────────────────


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Liveness + kernel state. Polled by the Tauri shell and the frontend."""
    return HealthResponse(
        status="ok",
        version=MANAGER_VERSION,
        binary=BinaryStatus(**binary_status.library_snapshot()),
    )


@app.post("/api/shutdown")
async def shutdown_endpoint():
    """Graceful shutdown — called by the Tauri shell when the window closes."""
    logger.info("Shutdown requested via API")
    request_shutdown()
    return {"ok": True}


# ── CDP WebSocket Proxy ──────────────────────────────────────────────────────
# Simple bidirectional passthrough — CDP is standard JSON over WebSocket,
# no protocol translation needed (unlike VNC which requires RFB filtering).


@app.get("/api/profiles/{profile_id}/cdp")
async def cdp_info(profile_id: str):
    """Return CDP connection info. Prevents SPA catch-all from serving index.html."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    return {
        "cdp_url": f"/api/profiles/{profile_id}/cdp",
        "usage": "playwright.chromium.connect_over_cdp('http://<host>/api/profiles/"
        + profile_id + "/cdp')",
    }


@app.get("/api/profiles/{profile_id}/cdp/json/version/")
@app.get("/api/profiles/{profile_id}/cdp/json/version")
async def cdp_json_version(profile_id: str, request: Request):
    """Proxy Chrome's /json/version, rewriting WS URLs to go through our proxy."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    # Rewrite webSocketDebuggerUrl to point through our proxy
    host = request.headers.get("host", "127.0.0.1:8000")
    data["webSocketDebuggerUrl"] = f"ws://{host}/api/profiles/{profile_id}/cdp"
    return data


@app.get("/api/profiles/{profile_id}/cdp/json/list/")
@app.get("/api/profiles/{profile_id}/cdp/json/list")
@app.get("/api/profiles/{profile_id}/cdp/json/")
@app.get("/api/profiles/{profile_id}/cdp/json")
async def cdp_json_list(profile_id: str, request: Request):
    """Proxy Chrome's /json/list, rewriting WS URLs."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/list", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    host = request.headers.get("host", "127.0.0.1:8000")
    for entry in data:
        if "webSocketDebuggerUrl" in entry:
            ws_path = entry["webSocketDebuggerUrl"].split("/devtools/")[-1]
            entry["webSocketDebuggerUrl"] = (
                f"ws://{host}/api/profiles/{profile_id}/cdp/devtools/{ws_path}"
            )
    return data


async def _proxy_cdp_websocket(
    websocket: WebSocket, target_url: str, label: str,
) -> None:
    """Bidirectional WebSocket proxy between a FastAPI client and a CDP target.

    Used by both browser-level and page-level CDP proxy endpoints.
    """
    import websockets

    try:
        async with websockets.connect(
            target_url, max_size=None, ping_interval=None, ping_timeout=None
        ) as cdp_ws:
            logger.info("%s: connected to %s", label, target_url)

            async def client_to_cdp():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg and msg["text"]:
                            await cdp_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"]:
                            await cdp_ws.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [c->cdp]: %s: %s", label, type(exc).__name__, exc)

            async def cdp_to_client():
                try:
                    async for msg in cdp_ws:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [cdp->c]: %s: %s", label, type(exc).__name__, exc)

            c2d = asyncio.create_task(client_to_cdp(), name="c2d")
            d2c = asyncio.create_task(cdp_to_client(), name="d2c")
            done, pending = await asyncio.wait(
                [c2d, d2c], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            logger.info("%s: disconnected", label)

    except Exception as exc:
        logger.error("%s error: %s", label, exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("%s: websocket.close() failed: %s", label, exc)


@app.websocket("/api/profiles/{profile_id}/cdp")
async def cdp_proxy(websocket: WebSocket, profile_id: str):
    """Proxy WebSocket frames between external tools and Chrome's CDP."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return

    await websocket.accept()

    # Get browser-level CDP WebSocket URL from Chrome
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            ws_url = resp.json()["webSocketDebuggerUrl"]
    except Exception as exc:
        logger.error("CDP proxy: failed to get WS URL for %s: %s", profile_id, exc)
        await websocket.close(code=4005, reason="CDP not available")
        return

    await _proxy_cdp_websocket(websocket, ws_url, f"CDP proxy [{profile_id}]")


@app.websocket("/api/profiles/{profile_id}/cdp/devtools/{path:path}")
async def cdp_page_proxy(websocket: WebSocket, profile_id: str, path: str):
    """Proxy page-specific CDP WebSocket connections (e.g. /devtools/page/GUID)."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return

    await websocket.accept()

    target_url = f"ws://127.0.0.1:{running.cdp_port}/devtools/{path}"
    await _proxy_cdp_websocket(websocket, target_url, f"CDP page proxy [{profile_id}]")


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
