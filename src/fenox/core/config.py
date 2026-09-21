"""Configuration and durable state.

Everything that survives a restart lives under one data directory
(`$FENOX_DATA_DIR`, else `$XDG_DATA_HOME/fenox`, else `~/.local/share/fenox`):
settings, devices, projects and groups in a SQLite database, the owner
credential in a `0600` file. A legacy `~/.fenox.json` is imported once so
existing installs keep their devices and projects.

The CLI and the hub share one `Store`. Settings are a live mapping; devices,
projects and groups are read and written through explicit methods.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .db import Database

APP_NAME = "fenox"

DEFAULT_SETTINGS: dict = {
    "projects_dir": "",
    "remote_domain": "",
    "reach": "local",          # local | lan | remote
    "port": 8787,
    "adb_port": 5038,
}


def _normalize_device(device_id: str, entry: dict) -> dict:
    """Fill in the device `type` that the legacy schema left implicit."""
    data = dict(entry)
    if not data.get("type"):
        if data.get("ip"):
            data["type"] = "wireless"
        elif data.get("serial"):
            data["type"] = "usb"
        elif device_id == "emulator" or data.get("port"):
            data["type"] = "emulator"
    return data


def _default_data_dir() -> Path:
    override = os.environ.get("FENOX_DATA_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


@dataclass(frozen=True)
class Paths:
    data: Path

    @property
    def db(self) -> Path:
        return self.data / "fenox.db"

    @property
    def auth(self) -> Path:
        return self.data / "auth.json"

    @property
    def sessions(self) -> Path:
        return self.data / "sessions"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def backups(self) -> Path:
        return self.data / "backups"


class _Settings(dict):
    """A settings mapping whose changes are written straight to the database."""

    def __init__(self, db: Database, initial: dict):
        super().__init__(initial)
        self._db = db

    def _persist(self, key: str) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(self[key])),
        )

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self._persist(key)

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        self._db.execute("DELETE FROM settings WHERE key = ?", (key,))

    def update(self, *args, **kwargs) -> None:
        incoming = dict(*args, **kwargs)
        super().update(incoming)
        for key in incoming:
            self._persist(key)


class Store:
    """Loads and persists the configuration for one data directory."""

    def __init__(self, data_dir: Path | str | None = None):
        self.paths = Paths(Path(data_dir).expanduser() if data_dir else _default_data_dir())
        self.paths.data.mkdir(parents=True, exist_ok=True)
        self.paths.sessions.mkdir(exist_ok=True)
        self.paths.logs.mkdir(exist_ok=True)
        self.db = Database(self.paths.db)
        self.settings: _Settings = _Settings(self.db, {})

    def load(self) -> Store:
        rows = self.db.query("SELECT key, value FROM settings")
        for row in rows:
            self.settings[row["key"]] = json.loads(row["value"])
        for key, value in DEFAULT_SETTINGS.items():
            if key not in self.settings:
                self.settings[key] = value
        self.import_legacy()
        return self

    # -- devices -----------------------------------------------------------
    def devices(self) -> dict:
        return {row["id"]: json.loads(row["data"]) for row in self.db.query("SELECT id, data FROM devices")}

    def device(self, device_id: str) -> dict | None:
        row = self.db.query_one("SELECT data FROM devices WHERE id = ?", (device_id,))
        return json.loads(row["data"]) if row else None

    def upsert_device(self, device_id: str, data: dict) -> None:
        self.db.execute(
            "INSERT INTO devices (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = datetime('now')",
            (device_id, json.dumps(data)),
        )

    def delete_device(self, device_id: str) -> None:
        self.db.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    # -- projects ----------------------------------------------------------
    def projects(self) -> dict:
        return {row["id"]: json.loads(row["data"]) for row in self.db.query("SELECT id, data FROM projects")}

    def project(self, project_id: str) -> dict | None:
        row = self.db.query_one("SELECT data FROM projects WHERE id = ?", (project_id,))
        return json.loads(row["data"]) if row else None

    def upsert_project(self, project_id: str, data: dict) -> None:
        self.db.execute(
            "INSERT INTO projects (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = datetime('now')",
            (project_id, json.dumps(data)),
        )

    def delete_project(self, project_id: str) -> None:
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # -- groups ------------------------------------------------------------
    def groups(self) -> dict[str, list[str]]:
        return {row["name"]: json.loads(row["data"]) for row in self.db.query("SELECT name, data FROM groups")}

    def set_group(self, name: str, members: list[str]) -> None:
        self.db.execute(
            "INSERT INTO groups (name, data) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET data = excluded.data",
            (name, json.dumps(members)),
        )

    def delete_group(self, name: str) -> None:
        self.db.execute("DELETE FROM groups WHERE name = ?", (name,))

    # -- run history -------------------------------------------------------
    def log_run(self, project: str, device: str | None, action: str, ok: bool = True) -> None:
        self.db.execute(
            "INSERT INTO runs (id, project, device, mode, status, started_at, ended_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{project}:{device or 'all'}:{action}:{int(time.time() * 1000)}",
                project,
                device or "all",
                action,
                "ok" if ok else "failed",
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                json.dumps({"ok": bool(ok)}),
            ),
        )

    def recent_runs(self, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            "SELECT id, project, device, mode, status, started_at FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # -- sessions ----------------------------------------------------------
    def upsert_session(self, session: dict) -> None:
        self.db.execute(
            "INSERT INTO sessions (id, project, device, mode, status, pid, argv, cwd, vm_service, devtools, "
            "exit_code, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, pid = excluded.pid, "
            "vm_service = excluded.vm_service, devtools = excluded.devtools, "
            "exit_code = excluded.exit_code, ended_at = excluded.ended_at",
            (
                session["id"],
                session["project"],
                session.get("device"),
                session.get("mode", "local"),
                session["status"],
                session.get("pid"),
                json.dumps(session.get("argv") or []),
                session.get("cwd"),
                session.get("vm_service"),
                session.get("devtools"),
                session.get("exit_code"),
                session["started_at"],
                session.get("ended_at"),
            ),
        )

    def session(self, session_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return dict(row) if row else None

    def sessions(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    def append_run_event(self, session_id: str, stream: str, line: str) -> None:
        self.db.execute(
            "INSERT INTO run_events (run_id, ts, stream, line) VALUES (?, ?, ?, ?)",
            (session_id, time.strftime("%Y-%m-%dT%H:%M:%S"), stream, line),
        )

    def run_events(self, session_id: str, limit: int = 2000) -> list[dict]:
        rows = self.db.query(
            "SELECT ts, stream, line FROM run_events WHERE run_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    # -- migration ---------------------------------------------------------
    def import_legacy(self) -> bool:
        """Import `~/.fenox.json` once, when this database is still empty."""
        if self.db.query_one("SELECT id FROM devices LIMIT 1") or self.db.query_one("SELECT id FROM projects LIMIT 1"):
            return False
        legacy = Path.home() / ".fenox.json"
        if not legacy.exists():
            return False
        try:
            data = json.loads(legacy.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        for device_id, entry in (data.get("devices") or {}).items():
            self.upsert_device(device_id, _normalize_device(device_id, entry))
        for name, members in (data.get("groups") or {}).items():
            if isinstance(members, list):
                self.set_group(name, members)
        settings = data.get("settings") or {}
        for key, value in settings.items():
            if key in DEFAULT_SETTINGS:
                self.settings[key] = value
        # `apps` in the old schema are `projects` now.
        for project_id, entry in (data.get("apps") or {}).items():
            self.upsert_project(project_id, entry)
        return True


_current: Store | None = None


def get_store() -> Store:
    """The process-wide store, created and loaded on first use."""
    global _current
    if _current is None:
        _current = Store().load()
    return _current


def set_store(store: Store) -> None:
    """Swap the process-wide store (used by the server factory and tests)."""
    global _current
    _current = store
