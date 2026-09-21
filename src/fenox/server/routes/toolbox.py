"""Per-device actions: screen, input, apps, control, and diagnostics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ...core import devices, mirror, phone, toolbox
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["toolbox"], dependencies=[Depends(require_owner)])


class InputAction(BaseModel):
    type: str
    text: str | None = None
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration: int | None = None
    key: str | None = None


class UrlAction(BaseModel):
    url: str


class ToggleAction(BaseModel):
    service: str
    enabled: bool


class LevelAction(BaseModel):
    level: int


class RebootAction(BaseModel):
    mode: str = ""


class ShellAction(BaseModel):
    command: str


class NotificationAction(BaseModel):
    title: str
    text: str


class InstallAction(BaseModel):
    path: str


def _serial(request: Request, device_id: str) -> str:
    serial = devices.live_serial(request.app.state.store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return serial


def _ok(result: tuple[bool, str], action: str) -> dict:
    ok, output = result
    if not ok:
        raise HTTPException(status_code=502, detail=output or f"{action} failed")
    return {"ok": True, "detail": output}


# -- screen and input ------------------------------------------------------

@router.post("/{device_id}/wake")
def wake(request: Request, device_id: str) -> dict:
    return _ok(toolbox.wake(_serial(request, device_id)), "wake")


@router.post("/{device_id}/lock")
def lock(request: Request, device_id: str) -> dict:
    return _ok(toolbox.lock(_serial(request, device_id)), "lock")


@router.post("/{device_id}/input")
def do_input(request: Request, device_id: str, body: InputAction) -> dict:
    serial = _serial(request, device_id)
    if body.type == "text" and body.text is not None:
        return _ok(toolbox.input_text(serial, body.text), "text")
    if body.type == "tap" and body.x is not None and body.y is not None:
        return _ok(toolbox.tap(serial, body.x, body.y), "tap")
    if body.type == "swipe":
        x, y, x2, y2 = body.x, body.y, body.x2, body.y2
        if x is None or y is None or x2 is None or y2 is None:
            raise HTTPException(status_code=422, detail="swipe needs x, y, x2 and y2")
        return _ok(toolbox.swipe(serial, x, y, x2, y2, body.duration or 300), "swipe")
    if body.type == "key" and body.key:
        return _ok(toolbox.keyevent(serial, body.key), "key")
    raise HTTPException(status_code=422, detail="unsupported input action")


@router.post("/{device_id}/open-url")
def open_url(request: Request, device_id: str, body: UrlAction) -> dict:
    return _ok(toolbox.open_url(_serial(request, device_id), body.url), "open url")


@router.get("/{device_id}/clipboard")
def read_clipboard(request: Request, device_id: str) -> dict:
    return {"clipboard": toolbox.clipboard_read(_serial(request, device_id))}


@router.post("/{device_id}/clipboard")
def write_clipboard(request: Request, device_id: str, body: InputAction) -> dict:
    if not body.text:
        raise HTTPException(status_code=422, detail="text is required")
    return _ok(toolbox.clipboard_set(_serial(request, device_id), body.text), "clipboard")


@router.get("/{device_id}/record")
def record_screen(request: Request, device_id: str, seconds: int = 10) -> Response:
    try:
        data = toolbox.record(_serial(request, device_id), seconds)
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=data, media_type="video/mp4")


# -- apps ------------------------------------------------------------------

@router.get("/{device_id}/apps")
def list_apps(request: Request, device_id: str, third_party: bool = True) -> dict:
    return {"apps": toolbox.list_packages(_serial(request, device_id), third_party=third_party)}


@router.post("/{device_id}/apps/install")
def install_app(request: Request, device_id: str, body: InstallAction) -> dict:
    return _ok(toolbox.install_apk(_serial(request, device_id), body.path), "install")


@router.post("/{device_id}/apps/{package}/uninstall")
def uninstall_app(request: Request, device_id: str, package: str) -> dict:
    return _ok(toolbox.uninstall(_serial(request, device_id), package), "uninstall")


@router.post("/{device_id}/apps/{package}/clear")
def clear_app(request: Request, device_id: str, package: str) -> dict:
    return _ok(toolbox.clear_data(_serial(request, device_id), package), "clear")


@router.post("/{device_id}/apps/{package}/stop")
def stop_app(request: Request, device_id: str, package: str) -> dict:
    return _ok(toolbox.force_stop(_serial(request, device_id), package), "stop")


@router.post("/{device_id}/apps/{package}/launch")
def launch_app(request: Request, device_id: str, package: str) -> dict:
    return _ok(toolbox.launch(_serial(request, device_id), package), "launch")


@router.get("/{device_id}/apps/{package}/info")
def app_info(request: Request, device_id: str, package: str) -> dict:
    ok, output = toolbox.app_info(_serial(request, device_id), package)
    if not ok:
        raise HTTPException(status_code=502, detail=output)
    return {"info": output}


# -- control ---------------------------------------------------------------

@router.post("/{device_id}/reboot")
def reboot(request: Request, device_id: str, body: RebootAction) -> dict:
    ok, output = toolbox.reboot(_serial(request, device_id), body.mode)
    if not ok:
        raise HTTPException(status_code=422, detail=output)
    return {"ok": True, "detail": output}


@router.post("/{device_id}/toggle")
def toggle(request: Request, device_id: str, body: ToggleAction) -> dict:
    serial = _serial(request, device_id)
    handlers = {
        "wifi": toolbox.toggle_wifi,
        "data": toolbox.toggle_data,
        "bluetooth": toolbox.toggle_bluetooth,
    }
    handler = handlers.get(body.service)
    if handler is None:
        raise HTTPException(status_code=422, detail="unsupported service")
    return _ok(handler(serial, body.enabled), body.service)


@router.post("/{device_id}/volume")
def volume(request: Request, device_id: str, body: LevelAction) -> dict:
    return _ok(toolbox.set_volume(_serial(request, device_id), body.level), "volume")


@router.post("/{device_id}/brightness")
def brightness(request: Request, device_id: str, body: LevelAction) -> dict:
    return _ok(toolbox.set_brightness(_serial(request, device_id), body.level), "brightness")


@router.post("/{device_id}/shell")
def run_shell(request: Request, device_id: str, body: ShellAction) -> dict:
    serial = _serial(request, device_id)
    ok, output = phone.shell(serial, body.command, timeout=60)
    return {"ok": ok, "output": output}


# -- mirroring -------------------------------------------------------------

@router.get("/{device_id}/mirror/status")
def mirror_status(request: Request, device_id: str) -> dict:
    ok, reason = mirror.available()
    return {
        "available": ok,
        "reason": reason,
        "version": mirror.scrcpy_version(),
        "active": device_id in request.app.state.mirrors,
    }


# -- diagnostics -----------------------------------------------------------

@router.get("/{device_id}/info")
def device_info(request: Request, device_id: str) -> dict:
    serial = _serial(request, device_id)
    return {
        "props": toolbox.device_props(serial),
        "battery": toolbox.battery(serial),
        "storage": toolbox.storage(serial),
    }


@router.get("/{device_id}/processes")
def device_processes(request: Request, device_id: str) -> dict:
    return {"processes": toolbox.processes(_serial(request, device_id))}


@router.post("/{device_id}/notification")
def send_notification(request: Request, device_id: str, body: NotificationAction) -> dict:
    return _ok(toolbox.send_notification(_serial(request, device_id), body.title, body.text), "notification")


@router.get("/{device_id}/notifications")
def read_notifications(request: Request, device_id: str) -> dict:
    return {"notifications": toolbox.read_notifications(_serial(request, device_id))}
