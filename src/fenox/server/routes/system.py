"""System information and health.

Kept deliberately read-only for now; guided tool installation arrives with M6.
"""
from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import doctor, host
from ...version import __version__
from ..security import require_owner

router = APIRouter(prefix="/api/system", tags=["system"])


class InstallRequest(BaseModel):
    tool: str


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


@router.get("/doctor")
def system_doctor(request: Request, _: None = Depends(require_owner)) -> dict:
    return doctor.checks(request.app.state.store.settings)


@router.post("/install")
def system_install(body: InstallRequest, _: None = Depends(require_owner)) -> dict:
    try:
        return doctor.run_install(body.tool)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tools")
def system_tools(request: Request, _: None = Depends(require_owner)) -> dict:
    """How adb, Flutter and scrcpy were resolved, and the candidates considered."""
    return doctor.tools(request.app.state.store.settings)
