"""Building a project: debug APK, release APK, release AAB.

A build is a long, one-shot, log-producing process, which makes it a sibling of
a `flutter run` session rather than a kind of it. The differences that matter:

* It has a **result**: an artifact on disk that someone wants to download, so the
  file is copied out of `build/` into the data directory the moment it is
  produced. Flutter's output directory is disposable — a `flutter clean`, or the
  next build of a different kind — and an artifact that vanishes when the user
  asks for it is worse than no artifact at all.
* It has a **kind**, and the kind decides the arguments *and* which API URLs are
  compiled in. A release build should point at production; a debug build at the
  local backend. Getting that backwards produces an app that runs and talks to
  the wrong server, which is hard to notice and easy to blame on the backend.
* It never needs a device, so it works with nothing plugged in.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import flutter as flutter_module
from .log import get_logger

log = get_logger("builds")

#: kind -> (label, flutter argv, artifact relative path, filename to keep)
KINDS: dict[str, dict] = {
    "apk-debug": {
        "label": "Debug APK",
        "argv": ["build", "apk", "--debug"],
        "artifact": "build/app/outputs/flutter-apk/app-debug.apk",
        "filename": "app-debug.apk",
        "mode": "local",
        "hint": "Fastest. Signed with the debug key, not for sharing.",
    },
    "apk-release": {
        "label": "Release APK",
        "argv": ["build", "apk", "--release"],
        "artifact": "build/app/outputs/flutter-apk/app-release.apk",
        "filename": "app-release.apk",
        "mode": "remote",
        "hint": "Installable by anyone. Needs your signing config for a store.",
    },
    "apk-profile": {
        "label": "Profile APK",
        "argv": ["build", "apk", "--profile"],
        "artifact": "build/app/outputs/flutter-apk/app-profile.apk",
        "filename": "app-profile.apk",
        "mode": "remote",
        "hint": "Release performance with tracing still on.",
    },
    "aab-release": {
        "label": "Release AAB",
        "argv": ["build", "appbundle", "--release"],
        "artifact": "build/app/outputs/bundle/release/app-release.aab",
        "filename": "app-release.aab",
        "mode": "remote",
        "hint": "The format Google Play accepts. Not installable directly.",
    },
}

TERMINAL = ("succeeded", "failed", "cancelled")

#: Enough history to scroll back through a build; the file keeps everything.
_BUFFER = 4000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Build:
    """One `flutter build` process, its output, and whatever it produced."""

    id: str
    project: str
    kind: str
    path: str
    status: str = "running"
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    exit_code: int | None = None
    artifact: str = ""
    artifact_name: str = ""
    artifact_size: int = 0
    artifact_sha256: str = ""
    error: str = ""

    _process: subprocess.Popen | None = None
    _reader: threading.Thread | None = None
    _subscribers: set[queue.Queue] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _lines: deque = field(default_factory=lambda: deque(maxlen=_BUFFER))

    # -- lifecycle ---------------------------------------------------------

    def run(self, argv: list[str], cwd: str, log_path: Path) -> None:
        self._process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, args=(log_path,), daemon=True)
        self._reader.start()

    def _pump(self, log_path: Path) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            with log_path.open("w", encoding="utf-8", errors="replace") as handle:
                for line in self._process.stdout:
                    stripped = line.rstrip("\n")
                    handle.write(stripped + "\n")
                    handle.flush()
                    self._emit(stripped)
        except Exception as exc:  # a broken pipe on cancel is expected
            log.debug("build %s reader stopped: %s", self.id, exc)
        finally:
            code = self._process.wait() if self._process else -1
            self._finish(code)

    def _finish(self, code: int) -> None:
        self.exit_code = code
        self.ended_at = _now()
        if self.status == "cancelled":
            pass
        elif code == 0:
            self.status = "succeeded"
            self._collect_artifact()
        else:
            self.status = "failed"
            self.error = f"flutter build exited with code {code}"
        self._notify({"type": "exit", "id": self.id, "status": self.status, "exit_code": code})

    def _collect_artifact(self) -> None:
        """Copy the output into the data directory, where it stays put.

        Flutter's `build/` directory is working space: a clean wipes it, and the
        next build for a different kind overwrites parts of it. An artifact the
        user is told about has to outlive that.
        """
        spec = KINDS.get(self.kind) or {}
        source = Path(self.path) / str(spec.get("artifact", ""))
        if not source.is_file():
            self.status = "failed"
            self.error = f"the build reported success but produced no file at {spec.get('artifact')}"
            return
        destination = self._storage_dir() / str(spec.get("filename") or source.name)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            self.artifact = str(destination)
            self.artifact_name = destination.name
            self.artifact_size = destination.stat().st_size
            self.artifact_sha256 = _sha256(destination)
        except OSError as exc:
            self.status = "failed"
            self.error = f"could not keep the built file: {exc}"

    #: Where this build's log and artifact live. Set by the manager.
    _storage: Path = field(default_factory=lambda: Path("."))

    def _storage_dir(self) -> Path:
        return self._storage

    # -- control -----------------------------------------------------------

    def cancel(self) -> bool:
        with self._lock:
            if self.status in TERMINAL or self._process is None:
                return False
            self.status = "cancelled"
            self._process.terminate()
            return True

    # -- subscribers -------------------------------------------------------

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
        self._notify({"type": "log", "stream": "stdout", "line": line})

    def _notify(self, message: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                pass

    def transcript(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "kind": self.kind,
            "label": (KINDS.get(self.kind) or {}).get("label", self.kind),
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "artifact": self.artifact,
            "artifact_name": self.artifact_name,
            "artifact_size": self.artifact_size,
            "artifact_sha256": self.artifact_sha256,
            "error": self.error,
            "path": self.path,
        }


class BuildManager:
    """Live builds, and the history of the ones that have finished."""

    def __init__(self, store, data_dir: Path):
        self.store = store
        self.root = Path(data_dir) / "builds"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._live: dict[str, Build] = {}
        self._index: list[dict] = self._load_index()

    # -- persistence -------------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> list[dict]:
        try:
            return list(json.loads(self._index_path.read_text()))
        except (OSError, ValueError):
            return []

    def _save_index(self) -> None:
        """Write via a temporary file so a crash cannot truncate the history."""
        try:
            temporary = self._index_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._index, indent=2))
            os.replace(temporary, self._index_path)
        except OSError as exc:
            log.warning("could not save the build history: %s", exc)

    def _remember(self, build: Build) -> None:
        row = build.as_dict()
        with self._lock:
            self._index = [entry for entry in self._index if entry["id"] != build.id]
            self._index.insert(0, row)
            self._index = self._index[:200]
            self._save_index()

    # -- queries -----------------------------------------------------------

    def get(self, build_id: str) -> Build | None:
        with self._lock:
            if build_id in self._live:
                return self._live[build_id]
        return None

    def row(self, build_id: str) -> dict | None:
        live = self.get(build_id)
        if live is not None:
            return live.as_dict()
        with self._lock:
            return next((entry for entry in self._index if entry["id"] == build_id), None)

    def listing(self, project: str | None = None) -> list[dict]:
        rows: list[dict] = []
        with self._lock:
            for build in self._live.values():
                if project is None or build.project == project:
                    rows.append(build.as_dict())
            for entry in self._index:
                if project is None or entry["project"] == project:
                    if not any(row["id"] == entry["id"] for row in rows):
                        rows.append(entry)
        rows.sort(key=lambda row: row.get("started_at") or "", reverse=True)
        return rows

    def artifact(self, build_id: str) -> Path | None:
        row = self.row(build_id)
        if not row or not row.get("artifact"):
            return None
        path = Path(row["artifact"])
        return path if path.is_file() else None

    def remove(self, build_id: str) -> bool:
        """Forget a build and delete the files it produced."""
        with self._lock:
            live = self._live.pop(build_id, None)
            if live is not None:
                live.cancel()
            before = len(self._index)
            self._index = [entry for entry in self._index if entry["id"] != build_id]
            changed = len(self._index) != before
            self._save_index()
        shutil.rmtree(self.root / build_id, ignore_errors=True)
        return changed or live is not None

    # -- starting ----------------------------------------------------------

    def start(self, project_id: str, kind: str, entry: dict, settings: dict) -> Build:
        spec = KINDS.get(kind)
        if spec is None:
            raise KeyError(f"unknown build kind: {kind}")

        path = os.path.expanduser(str(entry.get("path") or ""))
        binary = flutter_module.resolve(settings.get("flutter_path"), entry.get("path"))
        issues = flutter_module.preflight(binary, entry)
        if issues:
            raise ValueError("; ".join(issues))
        assert binary is not None

        # The kind decides which backend the app is built against. A release
        # build pointing at localhost is the kind of mistake that ships.
        mode = str(spec.get("mode") or "remote")
        argv = flutter_module.build_argv(binary, entry, kind=kind, mode=mode)

        build_id = f"{project_id}-{int(time.time() * 1000) % 100000000}"
        build = Build(id=build_id, project=project_id, kind=kind, path=path)
        build._storage = self.root / build_id
        build._storage.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._live[build_id] = build
        log.info("build %s (%s) in %s", build_id, kind, path)
        build.run(argv, path, build._storage / "build.log")

        # Persist as soon as it starts, so a hub restart leaves a record of it
        # rather than a build that silently never existed.
        self._remember(build)
        threading.Thread(target=self._await, args=(build,), daemon=True).start()
        return build

    def _await(self, build: Build) -> None:
        if build._reader is not None:
            build._reader.join()
        self._remember(build)
        with self._lock:
            self._live.pop(build.id, None)

    def shutdown(self) -> None:
        with self._lock:
            live = list(self._live.values())
        for build in live:
            build.cancel()
