"""Track CloakBrowser binary readiness and download it in the background.

The binary is downloaded from official channels on first run (~200 MB).
`ensure_binary()` is idempotent — on warm starts it returns quickly, so
`start()` is safe to call on every launch regardless of mode.

预检（Task 1）：若 cloakbrowser.download 提供了就绪查询函数（如 binary_path），
可在 start() 里先做一次同步存在性检查，命中则直接 ready=True 而不起后台任务。
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("cloakbrowser.manager.binary")


class BinaryManager:
    def __init__(self) -> None:
        self.ready: bool = False
        self.downloading: bool = False
        self.error: str | None = None
        self._task: asyncio.Task | None = None

    def status(self) -> dict[str, object]:
        return {"ready": self.ready, "downloading": self.downloading, "error": self.error}

    def start(self) -> None:
        """Kick off a background download unless already ready or in flight."""
        if self.ready or self.downloading:
            return
        self.downloading = True
        self.error = None
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            from cloakbrowser.download import ensure_binary

            await asyncio.to_thread(ensure_binary)
            self.ready = True
            logger.info("CloakBrowser binary is ready")
        except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
            self.error = str(exc)
            logger.error("Binary download failed: %s", exc)
        finally:
            self.downloading = False

    def reset(self) -> None:
        """Forget readiness so the next start() re-resolves the binary.

        Used when the kernel storage location changes at runtime. The download
        thread cannot be cancelled, so resetting mid-download is refused —
        callers must check `downloading` first.
        """
        if self.downloading:
            raise RuntimeError("cannot reset while a download is in flight")
        self.ready = False
        self.error = None
        self._task = None

    async def wait_ready(self) -> bool:
        """Await the in-flight download (if any) and report readiness."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        return self.ready
