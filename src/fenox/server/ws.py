"""WebSocket endpoints.

`/ws/events` streams device state so the dashboard updates without polling. Each
connection is authenticated with the same owner session cookie (or token) as the
REST API; an unauthenticated handshake is closed before any data is sent.
"""
from __future__ import annotations

import asyncio

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


def _snapshot(store) -> dict:
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
    return {
        "type": "devices",
        "devices": items,
        "pending": [{"id": i, "state": s} for i, s in adb.pending_devices()],
    }


@router.websocket("/ws/events")
async def events(websocket: WebSocket) -> None:
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    store = websocket.app.state.store
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_snapshot(store))
            await asyncio.sleep(EVENT_INTERVAL)
    except WebSocketDisconnect:
        return
