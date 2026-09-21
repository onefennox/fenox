"""SQLite storage with numbered migrations.

The hub and the CLI share one database file. It runs in WAL mode with a busy
timeout so a CLI command and the running hub can touch it at the same time
without corrupting anything.

Schema changes are append-only: add a migration function to `MIGRATIONS`, never
edit an existing one. The applied version is recorded in `schema_version`.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

SCHEMA_VERSION = 2

_MIGRATION_1 = """
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE devices (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE projects (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE groups (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE runs (
    id         TEXT PRIMARY KEY,
    project    TEXT NOT NULL,
    device     TEXT,
    mode       TEXT NOT NULL,
    status     TEXT NOT NULL,
    pid        INTEGER,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    exit_code  INTEGER,
    data       TEXT
);

CREATE TABLE run_events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts     TEXT NOT NULL,
    stream TEXT NOT NULL,
    line   TEXT NOT NULL
);

CREATE INDEX idx_run_events_run ON run_events(run_id, id);
CREATE INDEX idx_runs_started ON runs(started_at DESC);
"""

_MIGRATION_2 = """
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    project    TEXT NOT NULL,
    device     TEXT,
    mode       TEXT NOT NULL,
    status     TEXT NOT NULL,
    pid        INTEGER,
    argv       TEXT,
    cwd        TEXT,
    vm_service TEXT,
    devtools   TEXT,
    exit_code  INTEGER,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);

CREATE INDEX idx_sessions_started ON sessions(started_at DESC);
"""


def _apply_migration_1(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIGRATION_1)


def _apply_migration_2(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIGRATION_2)


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _apply_migration_1),
    (2, _apply_migration_2),
]


class Database:
    """A thin, thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            current = row["version"] if row else 0
            for version, apply in MIGRATIONS:
                if version > current:
                    apply(self._conn)
                    current = version
            if row is None:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (current,))
            else:
                self._conn.execute("UPDATE schema_version SET version = ?", (current,))
            self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
