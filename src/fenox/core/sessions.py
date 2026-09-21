"""Run supervisor: spawn `flutter run`, stream it, and control it.

Each `(project, device)` pair is one session. The transport (pseudo-terminal and
signals, or pipes and stdin keys) lives in `session_io`; the supervisor only
decides when to reload, restart or stop, keeps a bounded transcript, and fans
output out to WebSocket subscribers.
"""
from __future__ import annotations

import os
import queue
import re
import signal
import threading
import time
from collections import deque
from datetime import datetime

from . import devices, flutter, session_io
from .session_io import SIGINT, SIGKILL, SIGTERM

BUFFER_LINES = 5000

_VM_SERVICE = re.compile(r"https?://127\.0\.0\.1:\d+/[A-Za-z0-9_\-]+/?")
_ANY_URL = re.compile(r"https?://[^\s\"']+")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Session:
    """One live `flutter run` process and its subscribers."""

    def __init__(self, manager: SessionManager, session_id: str, project_id: str, entry: dict,
                 device_id: str | None, serial: str, mode: str, argv: list[str]):
        self.manager = manager
        self.id = session_id
        self.project = project_id
        self.entry = entry
        self.device = device_id
        self.serial = serial
        self.mode = mode
        self.argv = argv
        self.cwd = os.path.expanduser(str(entry.get("path") or ""))
        self.status = "starting"
        self.pid: int | None = None
        self.vm_service: str | None = None
        self.devtools: str | None = None
        self.exit_code: int | None = None
        self.started_at = _now()
        self.ended_at: str | None = None

        self._buffer: deque[str] = deque(maxlen=BUFFER_LINES)
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.RLock()
        self._partial = ""
        self._stop_requested = False
        self._log_path = os.path.join(manager.state_dir, session_id, "output.log")
        self._pid_file = os.path.join(manager.state_dir, session_id, "flutter.pid")
        # The caller supplies the arguments without the pid file; append it here so
        # the path is always under our session directory.
        self._io = session_io.create_io([*argv, "--pid-file", self._pid_file], self.cwd, dict(os.environ))

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
        self._io.start()
        self._persist()

        threading.Thread(target=self._read_loop, daemon=True, name=f"fenox-log-{self.id}").start()
        threading.Thread(target=self._pid_loop, args=(self._pid_file,), daemon=True, name=f"fenox-pid-{self.id}").start()
        threading.Thread(target=self._wait_loop, daemon=True, name=f"fenox-wait-{self.id}").start()

    def _persist(self) -> None:
        self.manager.store.upsert_session(self.summary())

    def _pid_loop(self, pid_file: str) -> None:
        for _ in range(400):                       # up to ~40s for a cold build
            if self._stop_requested:
                return
            try:
                with open(pid_file) as handle:
                    content = handle.read().strip()
                if content.isdigit():
                    self.pid = int(content)
                    if self.status == "starting":
                        self.status = "running"
                        self._persist()
                        self._broadcast({"type": "status", **self.summary()})
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.1)

    def _read_loop(self) -> None:
        while True:
            chunk = self._io.read()
            if not chunk:
                break
            self._ingest(chunk.decode("utf-8", "replace"))
        if self._partial:
            self._on_line("stdout", self._partial)
            self._partial = ""

    def _ingest(self, text: str) -> None:
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            self._on_line("stdout", line.rstrip("\r"))

    def _on_line(self, stream: str, line: str) -> None:
        with self._lock:
            self._buffer.append(line)
        self._parse(line)
        try:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
        self._broadcast({"type": "log", "stream": stream, "line": line})

    def _parse(self, line: str) -> None:
        lowered = line.lower()
        if self.vm_service is None and "vm service" in lowered:
            match = _VM_SERVICE.search(line)
            if match:
                self.vm_service = match.group(0)
                self._persist()
                self._broadcast({"type": "status", **self.summary()})
        if self.devtools is None and "devtools" in lowered:
            match = _ANY_URL.search(line)
            if match:
                self.devtools = match.group(0).rstrip(".,")
                self._persist()
                self._broadcast({"type": "status", **self.summary()})

    def _wait_loop(self) -> None:
        code = self._io.wait()
        self._io.close()
        self.exit_code = code
        self.ended_at = _now()
        if self._stop_requested:
            self.status = "stopped"
        elif code == 0:
            self.status = "finished"
        else:
            self.status = "crashed"
        self._persist()
        self.manager._reap(self)
        self._broadcast({"type": "exit", **self.summary()})

    # -- control -----------------------------------------------------------
    def reload(self) -> bool:
        return self._control("USR1", b"r")

    def restart(self) -> bool:
        return self._control("USR2", b"R")

    def _control(self, signal_name: str, key: bytes) -> bool:
        number = getattr(signal, f"SIG{signal_name}", None)
        if self.pid and number is not None:
            try:
                os.kill(self.pid, number)
                return True
            except (ProcessLookupError, PermissionError):
                return False
        # No pid yet, or no signals on this platform: send the key Flutter reads.
        self._io.write(key)
        return True

    def stop(self, timeout: float = 8.0) -> None:
        self._stop_requested = True
        if self.status in ("starting", "running"):
            self.status = "stopping"
            self._persist()
            self._broadcast({"type": "status", **self.summary()})
        if self._io.poll() is not None:
            return
        for number in (SIGINT, SIGTERM):
            if self._io.poll() is not None:
                return
            self._io.signal_group(number)
            deadline = time.time() + timeout / 2
            while time.time() < deadline:
                if self._io.poll() is not None:
                    return
                time.sleep(0.1)
        if self._io.poll() is None:
            self._io.signal_group(SIGKILL)

    # -- subscribers -------------------------------------------------------
    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _broadcast(self, message: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(message)
                except queue.Empty:
                    pass

    def transcript(self, limit: int = BUFFER_LINES) -> list[str]:
        with self._lock:
            return list(self._buffer)[-limit:]

    def is_active(self) -> bool:
        return self.status in ("starting", "running", "stopping")

    def summary(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "device": self.device,
            "serial": self.serial,
            "mode": self.mode,
            "status": self.status,
            "pid": self.pid,
            "vm_service": self.vm_service,
            "devtools": self.devtools,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


class SessionManager:
    """Owns every run in this process and reconciles them with the database."""

    def __init__(self, store):
        self.store = store
        self.state_dir = str(store.paths.data / "sessions")
        os.makedirs(self.state_dir, exist_ok=True)
        self._active: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._mark_orphans()

    def _mark_orphans(self) -> None:
        for row in self.store.sessions(limit=200):
            if row["status"] in ("starting", "running", "stopping"):
                pid = row.get("pid")
                alive = bool(pid) and os.path.exists(f"/proc/{pid}")
                if not alive:
                    row["status"] = "lost"
                    row["ended_at"] = _now()
                    self.store.upsert_session(row)

    def start(self, project_id: str, device_id: str, mode: str = "local") -> Session:
        entry = self.store.project(project_id)
        if entry is None:
            raise KeyError(f"unknown project: {project_id}")

        flutter_bin = flutter.resolve(self.store.settings.get("flutter_path"), entry.get("path"))
        issues = flutter.preflight(flutter_bin, entry)
        if issues:
            raise ValueError("; ".join(issues))

        serial = devices.resolve_serial(self.store, device_id)
        if serial is None:
            raise ValueError(f"device '{device_id}' is not reachable")

        assert flutter_bin is not None
        session_id = f"{project_id}-{device_id}-{int(time.time() * 1000) % 100000000}"
        argv = flutter.run_argv(flutter_bin, entry, serial, mode)

        session = Session(self, session_id, project_id, entry, device_id, serial, mode, argv)
        with self._lock:
            self._active[session_id] = session
        session.start()
        return session

    def _reap(self, session: Session) -> None:
        with self._lock:
            self._active.pop(session.id, None)

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._active.get(session_id)

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            active = {session.id: session.summary() for session in self._active.values()}
        merged = []
        for row in self.store.sessions(limit=limit):
            summary = active.get(row["id"])
            if summary is not None:
                active.pop(row["id"])
                merged.append(summary)
            else:
                merged.append(_row_summary(row))
        merged.extend(active.values())
        return merged

    def stop(self, session_id: str) -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        session.stop()
        return True

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._active.values())
        for session in sessions:
            session.stop(timeout=4)


def _row_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "project": row["project"],
        "device": row["device"],
        "serial": None,
        "mode": row["mode"],
        "status": row["status"],
        "pid": row["pid"],
        "vm_service": row["vm_service"],
        "devtools": row["devtools"],
        "exit_code": row["exit_code"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
    }
