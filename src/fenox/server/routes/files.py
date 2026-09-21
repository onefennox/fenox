"""Browsing and transferring files on a device."""
from __future__ import annotations

import posixpath
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from ...core import devices, files
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["files"], dependencies=[Depends(require_owner)])


class PushRequest(BaseModel):
    local: str
    remote: str


class PullRequest(BaseModel):
    remote: str
    local: str


class PathRequest(BaseModel):
    path: str


def _serial(request: Request, device_id: str) -> str:
    serial = devices.live_serial(request.app.state.store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return serial


@router.get("/{device_id}/files")
def list_files(request: Request, device_id: str, path: str = "/sdcard") -> dict:
    entries, error = files.list_dir(_serial(request, device_id), path)
    if entries is None:
        raise HTTPException(status_code=502, detail=error)
    parent = posixpath.dirname(path.rstrip("/")) or "/"
    return {"path": path, "parent": parent, "entries": entries}


@router.get("/{device_id}/files/download")
def download_file(request: Request, device_id: str, path: str) -> Response:
    try:
        data = files.download(_serial(request, device_id), path)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    name = posixpath.basename(path.rstrip("/")) or "download"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.post("/{device_id}/files/push")
def push_file(request: Request, device_id: str, body: PushRequest) -> dict:
    ok, output = files.push(_serial(request, device_id), body.local, body.remote)
    if not ok:
        raise HTTPException(status_code=502, detail=output or "push failed")
    return {"ok": True, "detail": output}


@router.post("/{device_id}/files/upload")
async def upload_file(
    request: Request,
    device_id: str,
    path: str = "/sdcard",
    file_name: str = Header(alias="X-Filename"),
) -> dict:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="the uploaded file is empty")
    ok, output = files.upload(_serial(request, device_id), unquote(file_name), data, path)
    if not ok:
        raise HTTPException(status_code=502, detail=output or "upload failed")
    return {"ok": True, "detail": output}


@router.post("/{device_id}/files/pull")
def pull_file(request: Request, device_id: str, body: PullRequest) -> dict:
    ok, output = files.pull(_serial(request, device_id), body.remote, body.local)
    if not ok:
        raise HTTPException(status_code=502, detail=output or "pull failed")
    return {"ok": True, "detail": output}


@router.post("/{device_id}/files/mkdir")
def make_dir(request: Request, device_id: str, body: PathRequest) -> dict:
    ok, output = files.make_dir(_serial(request, device_id), body.path)
    if not ok:
        raise HTTPException(status_code=502, detail=output or "mkdir failed")
    return {"ok": True, "detail": output}


@router.delete("/{device_id}/files")
def remove_file(request: Request, device_id: str, path: str) -> dict:
    ok, output = files.remove(_serial(request, device_id), path)
    if not ok:
        raise HTTPException(status_code=502, detail=output or "remove failed")
    return {"ok": True, "detail": output}
