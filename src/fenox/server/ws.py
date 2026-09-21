"""WebSocket endpoints.

`/ws/events` streams device state so the dashboard updates without polling. Each
connection is authenticated with the same owner session cookie (or token) as the
REST API; an unauthenticated handshake is closed before any data is sent.
"""
from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core import adb, devices
from .security import COOKIE_NAME

router = APIRouter()

EVENT_INTERVAL = 2.0


def _authorized(websocket: WebSocket) -> bool:
    auth = websocket.app.state.auth
    if not auth.has_owner():
        return False
    cookie = websocket.cookies.get(COOKIE_NAME)
    if cookie and auth.verify_session(cookie):
        return True
    token = websocket.query_params.get("token")
    return auth.verify_token(token)


def _snapshot(store, manager) -> dict:
    connected = adb.connected_ids()
    items = []
    for alias, info in store.devices().items():
        serial = devices.live_serial(store, alias, connected)
        items.append({
            "id": alias,
            "type": info.get("type"),
            "model": info.get("model"),
            "serial": serial,
            "online": serial is not None,
        })
    sessions = [
        {
            "id": session["id"],
            "project": session["project"],
            "device": session["device"],
            "status": session["status"],
        }
        for session in manager.list(limit=20)
    ]
    return {
        "type": "devices",
        "devices": items,
        "pending": [{"id": i, "state": s} for i, s in adb.pending_devices()],
        "sessions": sessions,
    }


@router.websocket("/ws/events")
async def events(websocket: WebSocket) -> None:
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    store = websocket.app.state.store
    manager = websocket.app.state.sessions
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_snapshot(store, manager))
            await asyncio.sleep(EVENT_INTERVAL)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/runs/{run_id}")
async def run_stream(websocket: WebSocket, run_id: str) -> None:
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    manager = websocket.app.state.sessions
    store = websocket.app.state.store
    await websocket.accept()

    session = manager.get(run_id)
    if session is None:
        for event in store.run_events(run_id):
            await websocket.send_json({"type": "log", "stream": event["stream"], "line": event["line"]})
        await websocket.send_json({"type": "exit", "id": run_id, "status": "finished"})
        await websocket.close()
        return

    for line in session.transcript():
        await websocket.send_json({"type": "log", "stream": "stdout", "line": line})

    subscriber = session.subscribe()
    try:
        while True:
            try:
                message = await asyncio.to_thread(subscriber.get, True, 1.0)
            except queue.Empty:
                if not session.is_active():
                    break
                continue
            await websocket.send_json(message)
            if message.get("type") == "exit":
                break
    except WebSocketDisconnect:
        pass
    finally:
        session.unsubscribe(subscriber)
        try:
            await websocket.close()
        except RuntimeError:
            pass
