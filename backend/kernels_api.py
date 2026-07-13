"""REST endpoints for the kernel library."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from . import binary_status, database as db, kernel_manager
from .models import DownloadStatusResponse, KernelImportRequest, KernelResponse

logger = logging.getLogger("cloakbrowser.manager.kernels")

router = APIRouter(prefix="/api/kernels")


def _to_response(kernel: dict) -> KernelResponse:
    return KernelResponse(
        **kernel, valid=kernel_manager.kernel_is_valid(kernel["version"])
    )


@router.get("", response_model=list[KernelResponse])
async def list_kernels():
    return [_to_response(k) for k in db.list_kernels()]


@router.post("/import", response_model=KernelResponse, status_code=201)
async def import_kernel(req: KernelImportRequest):
    try:
        kernel = kernel_manager.import_kernel(req.path)
    except kernel_manager.KernelImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Imported kernel %s from %s", kernel["version"], req.path)
    return _to_response(kernel)


@router.post("/download")
async def download_kernel():
    if not binary_status.download.start():
        raise HTTPException(status_code=409, detail="A download is already in progress")
    return {"ok": True}


@router.get("/download/status", response_model=DownloadStatusResponse)
async def download_status():
    return DownloadStatusResponse(**binary_status.download.snapshot())


@router.put("/{kernel_id}/default")
async def set_default(kernel_id: str):
    if not db.set_default_kernel(kernel_id):
        raise HTTPException(status_code=404, detail="Kernel not found")
    return {"ok": True}


def _kernel_in_use(kernel_id: str) -> bool:
    """True if any currently running profile resolves to this kernel."""
    from .main import browser_mgr  # late import — main imports this module

    default = db.get_default_kernel()
    for profile_id in list(browser_mgr.running):
        profile = db.get_profile(profile_id)
        if profile is None:
            continue
        effective = profile.get("kernel_id") or (default["id"] if default else None)
        if effective == kernel_id:
            return True
    return False


@router.delete("/{kernel_id}")
async def delete_kernel(kernel_id: str):
    kernel = db.get_kernel(kernel_id)
    if not kernel:
        raise HTTPException(status_code=404, detail="Kernel not found")
    if _kernel_in_use(kernel_id):
        raise HTTPException(
            status_code=409, detail="Kernel is in use by a running profile"
        )
    db.delete_kernel(kernel_id)
    kernel_manager.remove_kernel_files(kernel)
    return {"ok": True}
