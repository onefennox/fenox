"""Screen mirroring over WebRTC, through MediaMTX.

The hub starts a per-device pipeline (scrcpy -> ffmpeg -> MediaMTX) and proxies
the WHEP handshake so the owner session guards it. The media itself flows
browser <-> MediaMTX directly over WebRTC.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...core import devices, mediamtx, mirror
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["mirror"], dependencies=[Depends(require_owner)])


def _serial(request: Request, device_id: str) -> str:
    serial = devices.live_serial(request.app.state.store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return serial


@router.get("/{device_id}/mirror/status")
def mirror_status(request: Request, device_id: str) -> dict:
    data_dir = request.app.state.store.paths.data
    ok, reason = mirror.available(data_dir)
    return {
        "available": ok,
        "reason": reason,
        "server_version": mirror.scrcpy_server.PINNED_VERSION,
        "mediamtx_version": mediamtx.PINNED_VERSION,
        "provisioned": mediamtx.cached(data_dir),
        "ffmpeg": mediamtx.ffmpeg_binary(),
        "active": device_id in request.app.state.mirrors,
    }


@router.post("/{device_id}/mirror")
def start_mirror(request: Request, device_id: str) -> dict:
    serial = _serial(request, device_id)
    # Replace any previous pipeline for this device rather than leaking it.
    previous = request.app.state.mirrors.pop(device_id, None)
    if previous is not None:
        previous.stop()
    session = mirror.MirrorSession(serial, device_id, request.app.state.mediamtx)
    try:
        session.start()
    except Exception as exc:
        session.stop()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    request.app.state.mirrors[device_id] = session
    return {"path": session.path, "whep": f"/api/devices/{device_id}/mirror/whep", "active": True}


@router.delete("/{device_id}/mirror")
def stop_mirror(request: Request, device_id: str) -> dict:
    session = request.app.state.mirrors.pop(device_id, None)
    if session is not None:
        session.stop()
    return {"active": False}


@router.post("/{device_id}/mirror/whep")
async def mirror_whep(request: Request, device_id: str) -> Response:
    session = request.app.state.mirrors.get(device_id)
    if session is None:
        raise HTTPException(status_code=409, detail="mirroring is not running for this device")
    offer = (await request.body()).decode("utf-8", "replace")
    if not offer.strip():
        raise HTTPException(status_code=422, detail="an SDP offer is required")
    try:
        answer = session.mediamtx.whep(session.path, offer)
    except mediamtx.ProvisionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=answer, media_type="application/sdp")
