"""System information and health.

Kept deliberately read-only for now; guided tool installation arrives with M6.
"""
from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, Request

from ...core import host
from ...version import __version__
from ..security import require_owner

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Unauthenticated liveness probe (systemd, Docker, the installer)."""
    return {"status": "ok", "version": __version__}


@router.get("")
def system_info(request: Request, _: None = Depends(require_owner)) -> dict:
    settings = request.app.state.store.settings
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": {
            "linux": host.IS_LINUX,
            "macos": host.IS_MACOS,
            "wsl": host.IS_WSL,
        },
        "adb": {
            "windows_exe": host.find_windows_adb(),
            "server_port": settings.get("adb_port"),
        },
        "data_dir": str(request.app.state.store.paths.data),
        "reach": settings.get("reach"),
        "port": settings.get("port"),
    }
