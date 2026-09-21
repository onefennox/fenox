"""Run sessions: start Flutter, control it, and read its transcript."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import adb, devices
from ..security import require_owner

router = APIRouter(prefix="/api/runs", tags=["runs"], dependencies=[Depends(require_owner)])


class RunCreate(BaseModel):
    project: str
    device: str
    mode: Literal["local", "remote"] = "local"


class RunBatch(BaseModel):
    project: str
    devices: list[str] | None = None
    mode: Literal["local", "remote"] = "local"


def _manager(request: Request):
    return request.app.state.sessions


@router.get("")
def list_runs(request: Request) -> dict:
    return {"runs": _manager(request).list()}


@router.post("", status_code=201)
def start_run(request: Request, body: RunCreate) -> dict:
    try:
        session = _manager(request).start(body.project, body.device, body.mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session.summary()


@router.post("/batch", status_code=201)
def start_batch(request: Request, body: RunBatch) -> dict:
    store = request.app.state.store
    manager = _manager(request)
    if body.devices:
        targets = body.devices
    else:
        connected = adb.connected_ids()
        targets = [
            alias for alias, info in store.devices().items()
            if devices.is_enabled(info) and devices.live_serial(store, alias, connected)
        ]
    started, failed = [], []
    for device_id in targets:
        try:
            started.append(manager.start(body.project, device_id, body.mode).summary())
        except (KeyError, ValueError) as exc:
            failed.append({"device": device_id, "error": str(exc)})
    return {"started": started, "failed": failed}


@router.get("/{run_id}")
def get_run(request: Request, run_id: str) -> dict:
    session = _manager(request).get(run_id)
    if session is not None:
        return session.summary()
    row = request.app.state.store.session(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {key: row[key] for key in
            ("id", "project", "device", "mode", "status", "pid", "vm_service", "devtools",
             "exit_code", "started_at", "ended_at")}


@router.get("/{run_id}/log")
def get_log(request: Request, run_id: str) -> dict:
    session = _manager(request).get(run_id)
    if session is not None:
        return {"lines": session.transcript()}
    events = request.app.state.store.run_events(run_id)
    return {"lines": [event["line"] for event in events]}


def _control(request: Request, run_id: str, action: str) -> dict:
    session = _manager(request).get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run is not active")
    if action == "reload":
        ok = session.reload()
    elif action == "restart":
        ok = session.restart()
    else:
        session.stop()
        ok = True
    if not ok:
        raise HTTPException(status_code=409, detail="the run is not ready for that action yet")
    return {"id": run_id, "action": action, "ok": True}


@router.post("/{run_id}/reload")
def reload_run(request: Request, run_id: str) -> dict:
    return _control(request, run_id, "reload")


@router.post("/{run_id}/restart")
def restart_run(request: Request, run_id: str) -> dict:
    return _control(request, run_id, "restart")


@router.post("/{run_id}/stop")
def stop_run(request: Request, run_id: str) -> dict:
    return _control(request, run_id, "stop")
