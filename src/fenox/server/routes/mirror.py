"""Screen mirroring control.

Starting a mirror runs the scrcpy -> ffmpeg pipeline for a device; the video is
streamed over /ws/mirror/{id} as fragmented MP4 for the browser to play.
"""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core import devices, mirror
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["mirror"], dependencies=[Depends(require_owner)])


def _serial(request: Request, device_id: str) -> str:
    serial = devices.live_serial(request.app.state.store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return serial


@router.get("/{device_id}/mirror/status")
def mirror_status(request: Request, device_id: str) -> dict:
    ok, reason = mirror.available()
    return {
        "available": ok,
        "reason": reason,
        "server_version": mirror.scrcpy_server.PINNED_VERSION,
        "ffmpeg": shutil.which("ffmpeg"),
        "active": device_id in request.app.state.mirrors,
    }


@router.post("/{device_id}/mirror")
def start_mirror(request: Request, device_id: str) -> dict:
    serial = _serial(request, device_id)
    # Replace any previous pipeline for this device rather than leaking it.
    previous = request.app.state.mirrors.pop(device_id, None)
    if previous is not None:
        previous.stop()
    session = mirror.MirrorSession(serial, device_id, request.app.state.store.paths.data)
    try:
        session.start()
    except Exception as exc:
        session.stop()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    request.app.state.mirrors[device_id] = session
    return {"active": True, "codec": session.codec}


@router.delete("/{device_id}/mirror")
def stop_mirror(request: Request, device_id: str) -> dict:
    session = request.app.state.mirrors.pop(device_id, None)
    if session is not None:
        session.stop()
    return {"active": False}
