"""System information and health.

Kept deliberately read-only for now; guided tool installation arrives with M6.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
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


def _capture_files() -> list[dict]:
    """Screenshots and recordings Fenox has taken, newest first."""
    rows: list[dict] = []
    for kind, directory in host.output_dirs().items():
        if kind == "logs" or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append({
                "name": path.name,
                "kind": kind,
                "path": str(path),
                "size": stat.st_size,
                "at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
    rows.sort(key=lambda row: row["at"], reverse=True)
    return rows


@router.get("/captures")
def system_captures(_: None = Depends(require_owner)) -> dict:
    """Screenshots and recordings, with where they live on disk."""
    return {"directory": str(host.capture_root()), "captures": _capture_files()[:200]}


@router.get("/captures/download")
def system_capture_download(path: str, _: None = Depends(require_owner)) -> FileResponse:
    """Serve one capture.

    The path is checked against the known capture directories rather than
    trusted: this route takes a filesystem path from the query string, so
    without that check it would read anything the hub can read.
    """
    target = Path(path).resolve()
    allowed = [directory.resolve() for kind, directory in host.output_dirs().items() if kind != "logs"]
    if not any(target == directory or directory in target.parents for directory in allowed):
        raise HTTPException(status_code=403, detail="that file is outside the Fenox output folders")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no such file")
    return FileResponse(target, filename=target.name)
