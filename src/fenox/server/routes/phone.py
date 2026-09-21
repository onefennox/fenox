"""The phone's own data: messages, calls, contacts, and calendar."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import devices, phone
from ..security import require_owner

router = APIRouter(prefix="/api/devices", tags=["phone"], dependencies=[Depends(require_owner)])


class SeenRequest(BaseModel):
    ids: list[str]


class EventRequest(BaseModel):
    title: str
    begin: int
    end: int
    calendar_id: int = 1


def _serial(request: Request, device_id: str) -> str:
    serial = devices.live_serial(request.app.state.store, device_id)
    if serial is None:
        raise HTTPException(status_code=409, detail="device is offline")
    return serial


def _require(rows, error: str) -> list:
    if rows is None:
        raise HTTPException(status_code=502, detail=error or "the phone refused the request")
    return rows


@router.get("/{device_id}/phone/messages")
def messages(request: Request, device_id: str, unread: bool = False, limit: int = 50) -> dict:
    serial = _serial(request, device_id)
    names = phone.contacts(serial)
    rows, error = phone.threads(serial, names, unread_only=unread, limit=limit)
    return {"threads": _require(rows, error)}


@router.get("/{device_id}/phone/messages/{thread_id}")
def conversation(request: Request, device_id: str, thread_id: str, limit: int = 50) -> dict:
    serial = _serial(request, device_id)
    names = phone.contacts(serial)
    rows, error = phone.thread_messages(serial, thread_id, names, limit=limit)
    return {"messages": _require(rows, error)}


@router.post("/{device_id}/phone/messages/{thread_id}/read")
def mark_read(request: Request, device_id: str, thread_id: str) -> dict:
    ok, message = phone.mark_thread_read(_serial(request, device_id), thread_id)
    if not ok:
        raise HTTPException(status_code=502, detail=message)
    return {"ok": True, "detail": message}


@router.get("/{device_id}/phone/calls")
def calls(request: Request, device_id: str, days: int = 30, kind: str | None = None,
          search: str | None = None, number: str | None = None, limit: int = 100) -> dict:
    serial = _serial(request, device_id)
    names = phone.contacts(serial)
    kinds = [kind] if kind else None
    rows, error = phone.calls(serial, names, kinds=kinds, days=days, search=search, number=number, limit=limit)
    return {"calls": _require(rows, error)}


@router.post("/{device_id}/phone/calls/seen")
def mark_calls_seen(request: Request, device_id: str, body: SeenRequest) -> dict:
    ok, message = phone.mark_calls_seen(_serial(request, device_id), body.ids)
    if not ok:
        raise HTTPException(status_code=502, detail=message)
    return {"ok": True, "detail": message}


@router.get("/{device_id}/phone/contacts")
def contacts(request: Request, device_id: str, search: str | None = None, limit: int = 200) -> dict:
    rows, error = phone.contact_rows(_serial(request, device_id), search=search, limit=limit)
    return {"contacts": _require(rows, error)}


@router.get("/{device_id}/phone/calendars")
def calendars(request: Request, device_id: str) -> dict:
    rows, error = phone.calendars(_serial(request, device_id))
    return {"calendars": _require(rows, error)}


@router.get("/{device_id}/phone/events")
def events(request: Request, device_id: str, days: int = 7, calendar_id: int | None = None,
           search: str | None = None) -> dict:
    rows, error = phone.events(_serial(request, device_id), days=days, calendar_id=calendar_id, search=search)
    return {"events": _require(rows, error)}


@router.post("/{device_id}/phone/events")
def add_event(request: Request, device_id: str, body: EventRequest) -> dict:
    ok, message = phone.add_event(_serial(request, device_id), body.title, body.begin, body.end, body.calendar_id)
    if not ok:
        raise HTTPException(status_code=502, detail=message)
    return {"ok": True, "detail": message}
