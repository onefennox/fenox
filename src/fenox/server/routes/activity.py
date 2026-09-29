"""One feed of what has been happening.

Fenox does most of its work in the background — builds finish, runs start and
stop, devices come and go — and until now each of those lived only on its own
page. This gathers them so the dashboard can answer "what changed" without you
having to remember where to look.

Sources already keep their own history, so nothing new is recorded here; the
work is merging four differently-shaped records into one shape the UI can list.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...core import adb
from ...core.log import get_logger
from ..security import require_owner

log = get_logger("activity")

router = APIRouter(prefix="/api/activity", tags=["activity"], dependencies=[Depends(require_owner)])

#: How many of each source to consider before merging.
PER_SOURCE = 25


def _build_items(request: Request) -> list[dict]:
    rows = request.app.state.builds.listing()[:PER_SOURCE]
    items = []
    for row in rows:
        status = row.get("status")
        items.append({
            "kind": "build",
            "id": row["id"],
            "title": f"{row.get('artifact_name') or row.get('label', 'Build')}",
            "detail": f"{row.get('label', 'Build')} · {row.get('project', '')}",
            "status": status,
            "at": row.get("ended_at") or row.get("started_at") or "",
            "href": f"/projects/{row.get('project', '')}",
        })
    return items


def _run_items(request: Request) -> list[dict]:
    rows = request.app.state.store.sessions(limit=PER_SOURCE)
    items = []
    for row in rows:
        items.append({
            "kind": "run",
            "id": row.get("id", ""),
            "title": f"{row.get('project', '')} on {row.get('device', '')}".strip(),
            "detail": f"{row.get('mode', '')} run".strip(),
            "status": row.get("status", ""),
            "at": row.get("ended_at") or row.get("started_at") or "",
            "href": f"/runs/{row.get('id', '')}",
        })
    return items


def _device_items(request: Request) -> list[dict]:
    """Current device state, so the feed is not silent on an idle machine."""
    store = request.app.state.store
    connected = set(adb.connected_ids())
    items = []
    for alias, info in store.devices().items():
        online = alias in connected or bool(info.get("serial") and info["serial"] in connected)
        items.append({
            "kind": "device",
            "id": alias,
            "title": alias,
            "detail": f"{info.get('type') or 'device'} · {'online' if online else 'offline'}",
            "status": "online" if online else "offline",
            "at": "",
            "href": f"/devices/{alias}",
        })
    return items


@router.get("")
def activity(request: Request, limit: int = 40) -> dict:
    """Recent builds and runs, newest first, plus current device state."""
    items = _build_items(request) + _run_items(request)
    # Devices carry no timestamp; they go last so they read as "current state"
    # rather than as something that just happened.
    devices = _device_items(request)
    items = [item for item in items if item["at"]]
    items.sort(key=lambda item: item["at"], reverse=True)
    return {"items": items[:limit], "devices": devices}
