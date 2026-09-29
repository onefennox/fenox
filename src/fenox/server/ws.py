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


@router.websocket("/ws/mirror/{device_id}")
async def mirror(websocket: WebSocket, device_id: str) -> None:
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    session = websocket.app.state.mirrors.get(device_id)
    await websocket.accept()
    if session is None:
        await websocket.send_json({"type": "error", "detail": "mirroring is not running for this device"})
        await websocket.close()
        return
    # The codec string first, then fragmented MP4 the browser appends to MSE.
    await websocket.send_json({"type": "codec", "codec": session.codec})
    try:
        while True:
            chunk = await asyncio.to_thread(session.read)
            if not chunk:
                break
            await websocket.send_bytes(chunk)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


@router.websocket("/ws/logcat/{device_id}")
async def logcat(websocket: WebSocket, device_id: str) -> None:
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    store = websocket.app.state.store
    serial = devices.live_serial(store, device_id)
    await websocket.accept()
    if serial is None:
        await websocket.send_json({"type": "error", "detail": "device is offline"})
        await websocket.close()
        return

    process = await asyncio.create_subprocess_exec(
        "adb", "-s", serial, "logcat", "-v", "time",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_json({"type": "log", "line": line.decode("utf-8", "replace").rstrip()})
    except WebSocketDisconnect:
        pass
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


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


@router.websocket("/ws/browser")
async def browser_socket(websocket: WebSocket) -> None:
    """Frame stream out, input events in, on one socket.

    One direction per task: only `pump` sends and only `listen` receives, which
    is the pattern Starlette's WebSocket supports safely.
    """
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    instance = websocket.app.state.browser

    try:
        await instance.start()
        instance.clear_frames()
        await instance.start_screencast()
    except Exception as exc:  # reported to the panel rather than only the log
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    async def pump() -> None:
        while True:
            try:
                frame = await instance.next_frame(timeout=10)
            except TimeoutError:
                continue
            await websocket.send_bytes(frame)

    async def listen() -> None:
        while True:
            message = await websocket.receive_json()
            kind = message.get("t")
            try:
                if kind == "click":
                    await instance.click(float(message["x"]), float(message["y"]))
                elif kind == "scroll":
                    await instance.scroll(
                        float(message["x"]), float(message["y"]),
                        float(message.get("dy", 0)), float(message.get("dx", 0)),
                    )
                elif kind == "text":
                    await instance.type_text(str(message.get("v", "")))
                elif kind == "device":
                    await instance.set_device(str(message.get("v", "")))
                    await instance.reload()
                elif kind == "navigate":
                    await instance.navigate(str(message.get("v", "")))
                elif kind == "key":
                    await instance.press(str(message.get("v", "")))
                elif kind == "back":
                    await instance.go_back()
                elif kind == "reload":
                    await instance.reload()
            except Exception as exc:
                # A single bad input must not tear down the stream.
                await websocket.send_json({"type": "input-error", "message": str(exc)})

    tasks = [asyncio.create_task(pump()), asyncio.create_task(listen())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        # The screencast is left running so a reconnect resumes instantly; the
        # frames are dropped by the bounded queue rather than piling up.


@router.websocket("/ws/builds/{build_id}")
async def build_stream(websocket: WebSocket, build_id: str) -> None:
    """Live build output, then the outcome.

    Replays the transcript first so a viewer that connects late — or reconnects —
    still sees the whole build rather than joining mid-sentence.
    """
    if not _authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    manager = websocket.app.state.builds
    build = manager.get(build_id)
    if build is None:
        row = manager.row(build_id)
        if row is None:
            await websocket.send_json({"type": "error", "message": "build not found"})
            await websocket.close()
            return
        log_path = manager.root / build_id / "build.log"
        if log_path.is_file():
            for line in log_path.read_text(errors="replace").splitlines():
                await websocket.send_json({"type": "log", "stream": "stdout", "line": line})
        await websocket.send_json(
            {"type": "exit", "id": build_id, "status": row.get("status"), "exit_code": row.get("exit_code")}
        )
        await websocket.close()
        return

    for line in build.transcript():
        await websocket.send_json({"type": "log", "stream": "stdout", "line": line})

    subscriber = build.subscribe()
    try:
        while True:
            while True:
                try:
                    message = subscriber.get_nowait()
                except queue.Empty:
                    break
                await websocket.send_json(message)
                if message.get("type") == "exit":
                    return
            # Yield to the loop; the subscriber queue is fed by the reader thread.
            await asyncio.sleep(0.15)
    except WebSocketDisconnect:
        pass
    finally:
        build.unsubscribe(subscriber)
