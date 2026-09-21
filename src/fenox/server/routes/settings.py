"""Reach, port, and token settings.

Reach changes are explicit and explained: the API says what becomes reachable and
whether a restart is needed, and keeps the owner login in front of everything.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import access
from ..security import require_owner

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_owner)])

EDITABLE = ("reach", "port", "remote_domain", "flutter_path", "adb_path")


class SettingsUpdate(BaseModel):
    reach: str | None = None
    port: int | None = None
    remote_domain: str | None = None
    flutter_path: str | None = None
    adb_path: str | None = None


def _view(request: Request) -> dict:
    store = request.app.state.store
    settings = store.settings
    reach = str(settings.get("reach") or "local")
    port = int(settings.get("port") or 8787)
    serving = getattr(request.app.state, "serving", {})
    reach_changed = serving.get("reach") not in (None, reach)
    port_changed = serving.get("port") not in (None, port)
    return {
        "reach": reach,
        "reach_label": access.REACH_LABELS.get(reach, reach),
        "reach_levels": [{"id": level, "label": access.REACH_LABELS[level]} for level in access.REACH_LEVELS],
        "port": port,
        "remote_domain": settings.get("remote_domain") or "",
        "flutter_path": settings.get("flutter_path") or "",
        "adb_path": settings.get("adb_path") or "",
        "urls": access.urls(reach, port),
        "notes": access.notes(reach),
        "token": request.app.state.auth.token(),
        "restart_required": bool(reach_changed or port_changed),
    }


@router.get("")
def get_settings(request: Request) -> dict:
    return _view(request)


@router.patch("")
def update_settings(request: Request, body: SettingsUpdate) -> dict:
    store = request.app.state.store
    if body.reach is not None:
        if not access.is_valid(body.reach):
            raise HTTPException(status_code=422, detail=f"reach must be one of {list(access.REACH_LEVELS)}")
        store.settings["reach"] = body.reach
    if body.port is not None:
        if not (1 <= body.port <= 65535):
            raise HTTPException(status_code=422, detail="port must be between 1 and 65535")
        store.settings["port"] = body.port
    if body.remote_domain is not None:
        store.settings["remote_domain"] = body.remote_domain.strip()
    if body.flutter_path is not None:
        store.settings["flutter_path"] = body.flutter_path.strip()
    if body.adb_path is not None:
        store.settings["adb_path"] = body.adb_path.strip()
    return _view(request)


@router.post("/token")
def rotate_token(request: Request) -> dict:
    token = request.app.state.auth.rotate_token()
    return {"token": token}
