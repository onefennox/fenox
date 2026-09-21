"""Device registry, discovery, connection, and per-device data."""
from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ...core import adb, devices
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(require_owner)])

VALID_TYPES = {"usb", "emulator", "wireless"}


class DeviceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    model: str | None = None
    serial: str | None = None
    ip: str | None = None
    port: str | None = None
    disabled: bool | None = None


class PairRequest(BaseModel):
    ip: str
    port: str
    code: str = Field(min_length=1)


def _view(store, alias: str, connected: list[str]) -> dict:
    info = store.device(alias) or {}
    serial = devices.live_serial(store, alias, connected)
    return {
        "id": alias,
        "type": info.get("type"),
        "model": info.get("model"),
        "serial": serial,
        "ip": info.get("ip"),
        "port": info.get("port"),
        "disabled": bool(info.get("disabled", False)),
        "online": serial is not None,
    }


@router.get("")
def list_devices(request: Request) -> dict:
    store = request.app.state.store
    connected = adb.connected_ids()
    items = [_view(store, alias, connected) for alias in store.devices()]
    return {"devices": items, "pending": [{"id": i, "state": s} for i, s in adb.pending_devices()]}


@router.post("/discover")
def discover(request: Request) -> dict:
    store = request.app.state.store
    added = devices.autodetect(store)
    wireless_added, pending = devices.autodetect_wireless(store, force=True)
    connected = adb.connected_ids()
    return {
        "added": added + wireless_added,
        "pending": [{"ip": ip, "port": port} for ip, port in pending],
        "devices": [_view(store, alias, connected) for alias in store.devices()],
    }


@router.get("/{device_id}")
def get_device(request: Request, device_id: str) -> dict:
    store = request.app.state.store
    if store.device(device_id) is None:
        raise HTTPException(status_code=404, detail="device not found")
    return _view(store, device_id, adb.connected_ids())


@router.patch("/{device_id}")
def update_device(request: Request, device_id: str, body: DeviceUpdate) -> dict:
    store = request.app.state.store
    info = store.device(device_id)
    if info is None:
        raise HTTPException(status_code=404, detail="device not found")

    target = device_id
    if body.name and body.name != device_id:
        if store.device(body.name) is not None:
            raise HTTPException(status_code=409, detail="a device with that name already exists")
        target = body.name

    updates = body.model_dump(exclude_none=True, exclude={"name"})
    if "type" in updates and updates["type"] not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {sorted(VALID_TYPES)}")
    info.update(updates)

    if target != device_id:
        # The alias is the key, so a rename is a new record and a removal of the old.
        store.delete_device(device_id)
    store.upsert_device(target, info)
    return _view(store, target, adb.connected_ids())


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(request: Request, device_id: str) -> Response:
    store = request.app.state.store
    if store.device(device_id) is None:
        raise HTTPException(status_code=404, detail="device not found")
    store.delete_device(device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{device_id}/connect")
def connect_device(request: Request, device_id: str) -> dict:
    store = request.app.state.store
    if store.device(device_id) is None:
        raise HTTPException(status_code=404, detail="device not found")
    serial = devices.resolve_serial(store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is not reachable")
    return {"id": device_id, "serial": serial, "online": True}


@router.post("/pair")
def pair_device(body: PairRequest) -> dict:
    """Pair a phone by IP, pairing port, and code. No prior registration needed."""
    ok, result = adb.pair(body.ip, body.port, body.code)
    if not ok:
        raise HTTPException(status_code=409, detail=result or "pairing failed")
    return {"paired": True, "detail": result}


@router.get("/{device_id}/telemetry")
def device_telemetry(request: Request, device_id: str) -> dict:
    store = request.app.state.store
    serial = devices.live_serial(store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return {"id": device_id, "serial": serial, "telemetry": devices.telemetry(serial)}


@router.get("/{device_id}/screenshot")
def device_screenshot(request: Request, device_id: str) -> Response:
    store = request.app.state.store
    serial = devices.live_serial(store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=20, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="screenshot timed out") from exc
    if result.returncode != 0 or not result.stdout.startswith(b"\x89PNG"):
        raise HTTPException(status_code=502, detail="could not read a screenshot from the device")
    return Response(content=result.stdout, media_type="image/png")
