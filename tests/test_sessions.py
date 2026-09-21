import os
import stat
import time
from pathlib import Path

from fenox.core import devices
from fenox.core.config import Store
from fenox.core.sessions import SessionManager

FAKE_FLUTTER = """#!/usr/bin/env python3
import os, signal, sys, time

argv = sys.argv
pid_file = argv[argv.index("--pid-file") + 1]


def on_reload(signum, frame):
    print("Reloaded 1 of 1 libraries", flush=True)


def on_restart(signum, frame):
    print("Restarting application", flush=True)


signal.signal(signal.SIGUSR1, on_reload)
signal.signal(signal.SIGUSR2, on_restart)

with open(pid_file, "w") as handle:
    handle.write(str(os.getpid()))

print("Launching lib/main.dart on device in debug mode...", flush=True)
print("The Dart VM service is listening on http://127.0.0.1:12345/AbCdEf/", flush=True)
while True:
    time.sleep(0.2)
"""


def _install_fake_flutter(tmp_path: Path, monkeypatch) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    flutter = bindir / "flutter"
    flutter.write_text(FAKE_FLUTTER)
    flutter.chmod(flutter.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


def _project(store: Store, tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    store.upsert_project("demo", {"path": str(project), "port": "4000", "api_local": "http://localhost:4000/api"})


def _wait_for(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    return None


def test_session_runs_reloads_and_stops(tmp_path, monkeypatch):
    _install_fake_flutter(tmp_path, monkeypatch)
    monkeypatch.setattr(devices, "resolve_serial", lambda store, alias: "emulator-5554" if alias == "phone" else None)

    store = Store(tmp_path).load()
    _project(store, tmp_path)
    manager = SessionManager(store)

    session = manager.start("demo", "phone", "local")
    assert _wait_for(lambda: session.status == "running" and session.vm_service)
    assert session.vm_service == "http://127.0.0.1:12345/AbCdEf/"
    assert "Launching lib/main.dart" in "\n".join(session.transcript())

    assert session.reload() is True
    assert _wait_for(lambda: "Reloaded 1 of 1 libraries" in "\n".join(session.transcript()))

    assert session.restart() is True
    assert _wait_for(lambda: "Restarting application" in "\n".join(session.transcript()))

    session.stop()
    assert _wait_for(lambda: not session.is_active())
    assert session.status == "stopped"
    assert manager.get(session.id) is None


def test_session_records_history(tmp_path, monkeypatch):
    _install_fake_flutter(tmp_path, monkeypatch)
    monkeypatch.setattr(devices, "resolve_serial", lambda store, alias: "emulator-5554")

    store = Store(tmp_path).load()
    _project(store, tmp_path)
    manager = SessionManager(store)
    session = manager.start("demo", "phone", "local")
    _wait_for(lambda: session.status == "running")
    session.stop()
    _wait_for(lambda: not session.is_active())

    history = store.sessions()
    assert history and history[0]["id"] == session.id
    assert history[0]["status"] == "stopped"


def test_orphan_sessions_are_marked_lost(tmp_path):
    store = Store(tmp_path).load()
    store.upsert_session({
        "id": "ghost", "project": "demo", "device": "phone", "mode": "local",
        "status": "running", "pid": 999999, "started_at": "2026-01-01T00:00:00",
    })
    SessionManager(store)
    assert store.session("ghost")["status"] == "lost"


def test_run_routes_start_control_and_stop(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fenox.server.app import create_app

    _install_fake_flutter(tmp_path, monkeypatch)
    monkeypatch.setattr(devices, "resolve_serial", lambda store, alias: "emulator-5554")

    app = create_app(data_dir=tmp_path / "data")
    project = tmp_path / "demo"
    project.mkdir()
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": "a-strong-owner-password"})
        client.app.state.store.upsert_project(
            "demo", {"path": str(project), "port": "4000", "api_local": "http://localhost:4000/api"}
        )

        created = client.post("/api/runs", json={"project": "demo", "device": "phone", "mode": "local"})
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]

        assert _wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "running")
        assert client.post(f"/api/runs/{run_id}/reload").status_code == 200
        assert client.get(f"/api/runs/{run_id}/log").json()["lines"]

        assert client.post(f"/api/runs/{run_id}/stop").status_code == 200
        assert _wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "stopped")


def test_start_rejects_an_unreachable_device(tmp_path, monkeypatch):
    _install_fake_flutter(tmp_path, monkeypatch)
    monkeypatch.setattr(devices, "resolve_serial", lambda store, alias: None)
    store = Store(tmp_path).load()
    _project(store, tmp_path)
    manager = SessionManager(store)
    try:
        manager.start("demo", "phone", "local")
    except ValueError as exc:
        assert "not reachable" in str(exc)
    else:
        raise AssertionError("expected a ValueError")
