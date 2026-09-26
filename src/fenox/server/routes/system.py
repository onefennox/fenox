"""System information and health.

Kept deliberately read-only for now; guided tool installation arrives with M6.
"""
from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import adb, connect, doctor, host, projects, usbipd
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


@router.get("/connection")
def system_connection(request: Request, _: None = Depends(require_owner)) -> dict:
    """Why devices are or are not reachable, and what Fenox can do about it.

    Returns findings rather than a single verdict, because "no devices" is not
    actionable on its own: the owner needs to be told which of a dozen possible
    causes applies and the one command that resolves it.
    """
    findings = connect.diagnose(request.app.state.store)
    return {
        "findings": [finding.as_dict() for finding in findings],
        "wireless": {
            "pairing": adb.mdns_pairing_candidates(),
            "connect": adb.mdns_candidates(),
        },
        "usbipd": {
            "relevant": host.IS_WSL,
            "installed": usbipd.installed(),
            "version": usbipd.version(),
        },
        "adb_version": adb.client_version(),
    }


class RepairRequest(BaseModel):
    id: str


@router.post("/connection/repair")
def system_repair(request: Request, body: RepairRequest, _: None = Depends(require_owner)) -> dict:
    """Act on one finding, then re-check and report what actually changed.

    The response distinguishes resolved / escalated / unchanged / blocked, so the
    UI can say what happened rather than showing a spinner and hoping.
    """
    for finding in connect.diagnose(request.app.state.store):
        if finding.id == body.id:
            return connect.verify(finding)
    raise HTTPException(status_code=404, detail="no such finding")


@router.post("/connection/fix")
def system_fix_all(request: Request, _: None = Depends(require_owner)) -> dict:
    """Run every automatic fix in turn, verifying each one."""
    return {"results": connect.fix_all()}


@router.get("/browse")
def system_browse(path: str | None = None, _: None = Depends(require_owner)) -> dict:
    """List subdirectories of `path` for the folder picker.

    Owner-only, like the rest of the hub: the hub can already run commands, so
    this is no broader than the trust model the product already assumes. No
    `path` means the home directory. A Flutter app root also comes back with a
    suggested project name, so choosing a folder can fill in the form.
    """
    try:
        listing = host.browse_dirs(path)
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=f"not a directory: {exc}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"cannot read: {exc}") from exc
    if listing["flutter"]:
        listing["suggested_name"] = projects.suggest_name(listing["path"])
    return listing
