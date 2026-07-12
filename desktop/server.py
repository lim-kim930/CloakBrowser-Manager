"""Run the FastAPI backend in a background thread for the desktop client."""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
import urllib.request

logger = logging.getLogger("cloakbrowser.desktop.server")


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


class ServerHandle:
    def __init__(self) -> None:
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self, port: int) -> None:
        import uvicorn

        from backend.main import app

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            config = uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
            )
            self._server = uvicorn.Server(config)
            loop.run_until_complete(self._server.serve())

        self._thread = threading.Thread(target=run, daemon=True, name="uvicorn")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal uvicorn to exit; its lifespan shutdown closes all browsers."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
