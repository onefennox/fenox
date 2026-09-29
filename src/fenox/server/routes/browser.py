"""The embedded browser: a real Chrome, shown in the dashboard.

The heavy lifting is in `core.browser`; this is the adapter. Frames travel over
one WebSocket and input travels back on the same socket, so a viewer is always
in step with what it is looking at.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import browser
from ...core.log import get_logger
from ..security import require_owner

log = get_logger("browser.api")

router = APIRouter(prefix="/api/browser", tags=["browser"], dependencies=[Depends(require_owner)])


def _manager(request: Request) -> browser.Browser:
    return request.app.state.browser


@router.get("")
def browser_status(request: Request) -> dict:
    """Whether a browser is running, and what the panel can offer."""
    instance = _manager(request)
    return {
        "available": instance.available(),
        "running": bool(instance.state.running and instance.process and instance.process.poll() is None),
        "url": instance.state.url,
        "device": instance.state.device,
        "error": instance.state.error,
        "devices": [
            {"id": key, "label": spec["label"], "width": spec["width"], "height": spec["height"]}
            for key, spec in browser.DEVICES.items()
        ],
    }


class NavigateRequest(BaseModel):
    url: str


class DeviceRequest(BaseModel):
    device: str


@router.post("/start")
async def browser_start(request: Request) -> dict:
    instance = _manager(request)
    if not instance.available():
        raise HTTPException(
            status_code=409,
            detail="No Chrome or Chromium was found on this machine. Install one, or set FENOX_CHROME.",
        )
    try:
        await instance.start()
    except browser.CdpError as exc:
        instance.state.error = str(exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"running": True, "device": instance.state.device}


@router.post("/navigate")
async def browser_navigate(request: Request, body: NavigateRequest) -> dict:
    instance = _manager(request)
    try:
        await instance.start()
        # The override is re-applied on every navigation, because Chrome can
        # discard it when the document changes.
        await instance.set_device(instance.state.device)
        await instance.navigate(body.url)
    except browser.CdpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"url": instance.state.url}


@router.post("/device")
async def browser_device(request: Request, body: DeviceRequest) -> dict:
    instance = _manager(request)
    if body.device not in browser.DEVICES:
        raise HTTPException(status_code=422, detail=f"unknown device: {body.device}")
    try:
        await instance.start()
        await instance.set_device(body.device)
        await instance.reload()  # a viewport change only takes effect on a fresh layout
    except browser.CdpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"device": instance.state.device}


@router.post("/back")
async def browser_back(request: Request) -> dict:
    instance = _manager(request)
    try:
        await instance.go_back()
    except browser.CdpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/reload")
async def browser_reload(request: Request) -> dict:
    instance = _manager(request)
    try:
        await instance.reload()
    except browser.CdpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/stop")
async def browser_stop(request: Request) -> dict:
    """Shut the browser down and free the memory it holds."""
    await _manager(request).stop()
    return {"running": False}
