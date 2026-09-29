"""Builds: starting one, streaming it, and getting the artifact out.

A real `flutter build` needs the SDK and minutes. These tests use a stand-in
that writes the same log lines and creates the same output file, so the whole
path — preflight, arguments, process, artifact collection, hashing, download —
is exercised without either.
"""
from __future__ import annotations

import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fenox.core import builds, flutter
from fenox.server.app import create_app
from fenox.server.routes import builds as builds_module

PASSWORD = "a-strong-owner-password"


def make_project(root: Path, name: str = "demo") -> Path:
    project = root / name
    (project / "android").mkdir(parents=True)
    (project / "pubspec.yaml").write_text("name: demo\nversion: 1.0.0+1\n")
    return project


def make_fake_flutter(
    root: Path, *, fail: bool = False, omit_artifact: bool = False, sleep: int = 0
) -> Path:
    """A stand-in for the SDK that behaves like `flutter build`.

    It writes whichever artifact the requested command would, so a test of the
    AAB path produces an AAB rather than a build that failed for an unrelated
    reason.
    """
    root.mkdir(parents=True, exist_ok=True)
    script = root / "fake-flutter"
    lines = [
        "#!/bin/sh",
        'echo "Running Gradle task assembleDebug..."',
        'echo "Running with sound null safety"',
    ]
    if sleep:
        # A window in which the build is still running, which a fast script
        # cannot provide.
        lines.append(f"sleep {sleep}")
    if not omit_artifact:
        lines += [
            'case "$*" in',
            "  *appbundle*)",
            "    mkdir -p build/app/outputs/bundle/release",
            '    printf "FAKE-AAB-CONTENTS" > build/app/outputs/bundle/release/app-release.aab',
            "    ;;",
            "  *)",
            "    mkdir -p build/app/outputs/flutter-apk",
            '    printf "FAKE-APK-CONTENTS" > build/app/outputs/flutter-apk/app-debug.apk',
            "    ;;",
            "esac",
        ]
    lines.append("exit 1" if fail else "exit 0")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A hub with a project registered and a fake Flutter on it."""
    project = make_project(tmp_path)
    fake = make_fake_flutter(tmp_path / "bin")
    monkeypatch.setattr(flutter, "resolve", lambda configured, project_path: str(fake))

    app = create_app(data_dir=tmp_path / "data")
    client = TestClient(app)
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    client.post("/api/projects", json={"name": "demo", "path": str(project)})
    client.fake_flutter = fake  # type: ignore[attr-defined]
    client.project = project  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.state.builds.shutdown()
        client.__exit__(None, None, None)


def wait_for(build_id: str, manager, timeout: float = 20.0) -> dict:
    """A build runs in a thread; wait for it to reach a terminal state.

    Reads the *record* rather than the live object, because a fast build moves
    out of the live map and into history before the first poll — so asking only
    the live map would report "gone" for a build that succeeded instantly.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = manager.row(build_id)
        if row and row["status"] in builds.TERMINAL:
            return row
        time.sleep(0.05)
    raise AssertionError(f"build {build_id} did not finish in {timeout}s")


# --- the catalogue ----------------------------------------------------------

def test_every_kind_has_an_artifact_path_and_a_mode():
    """A kind without an artifact path would build and then have nothing to serve."""
    for kind, spec in builds.KINDS.items():
        assert spec["artifact"], f"{kind} has no artifact path"
        assert spec["mode"] in ("local", "remote"), f"{kind} has no backend mode"
        assert spec["argv"][:1] == ["build"], f"{kind} is not a build command"


def test_release_kinds_are_built_against_production():
    """A release build carrying a localhost URL ships an app that talks to nothing."""
    entry = {"api_local": "http://localhost:1991", "api_remote": "https://api.example.com"}

    release = " ".join(flutter.build_argv("flutter", entry, kind="apk-release", mode="remote"))
    debug = " ".join(flutter.build_argv("flutter", entry, kind="apk-debug", mode="local"))

    assert "https://api.example.com" in release
    assert "localhost" not in release
    assert "http://localhost:1991" in debug


def test_aab_uses_the_bundle_command():
    argv = flutter.build_argv("flutter", {}, kind="aab-release", mode="remote")

    assert argv[1:3] == ["build", "appbundle"]


# --- starting ---------------------------------------------------------------

def test_build_produces_an_artifact_that_can_be_downloaded(client):
    started = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"})
    assert started.status_code == 201
    build_id = started.json()["id"]

    build = wait_for(build_id, client.app.state.builds)
    assert build["status"] == "succeeded", build.get("error")

    row = client.get(f"/api/builds/{build_id}").json()
    # The artifact is copied out of build/, so a later `flutter clean` cannot
    # take away something the user was told about.
    assert row["artifact_name"] == "app-debug.apk"
    assert row["artifact_size"] > 0
    assert len(row["artifact_sha256"]) == 64
    assert not Path(row["artifact"]).is_relative_to(client.project), "artifact should live in the data dir"

    download = client.get(f"/api/builds/{build_id}/artifact")
    assert download.status_code == 200
    assert download.content == b"FAKE-APK-CONTENTS"
    assert "app-debug.apk" in download.headers["content-disposition"]


def test_a_failing_build_is_reported_as_failed_without_an_artifact(client, monkeypatch):
    monkeypatch.setattr(flutter, "resolve", lambda c, p: str(make_fake_flutter(client.project.parent / "bad", fail=True)))

    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    build = wait_for(build_id, client.app.state.builds)

    assert build["status"] == "failed"
    assert build["exit_code"] == 1
    assert client.get(f"/api/builds/{build_id}/artifact").status_code == 404


def test_success_with_no_file_on_disk_is_not_called_a_success(client, monkeypatch):
    """Exit 0 but nothing produced is a failure, not a build with an empty artifact."""
    monkeypatch.setattr(
        flutter, "resolve", lambda c, p: str(make_fake_flutter(client.project.parent / "empty", omit_artifact=True))
    )

    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    build = wait_for(build_id, client.app.state.builds)

    assert build["status"] == "failed"
    assert "no file" in build["error"]


def test_the_log_is_captured_and_served(client):
    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    wait_for(build_id, client.app.state.builds)

    lines = client.get(f"/api/builds/{build_id}/log").json()["lines"]

    assert any("Gradle" in line for line in lines)


# --- refusals, which have to be clear rather than 500s ----------------------

def test_unknown_project_is_404(client):
    assert client.post("/api/projects/nope/builds", json={"kind": "apk-debug"}).status_code == 404


def test_unknown_kind_is_422(client):
    assert client.post("/api/projects/demo/builds", json={"kind": "exe"}).status_code == 422


def test_missing_flutter_is_a_409_with_a_reason(client, monkeypatch):
    monkeypatch.setattr(flutter, "resolve", lambda c, p: None)

    response = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"})

    assert response.status_code == 409
    assert "flutter" in response.json()["detail"].lower()


def test_artifact_for_a_build_without_one_is_404(client):
    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    wait_for(build_id, client.app.state.builds)
    # Delete the recorded file to stand in for a build that produced nothing
    # usable; the route must say so rather than serve a missing path.
    Path(client.get(f"/api/builds/{build_id}").json()["artifact"]).unlink()

    assert client.get(f"/api/builds/{build_id}/artifact").status_code == 404


# --- history ----------------------------------------------------------------

def test_builds_are_listed_newest_first_and_removable(client):
    first = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    wait_for(first, client.app.state.builds)
    second = client.post("/api/projects/demo/builds", json={"kind": "apk-release"}).json()["id"]
    wait_for(second, client.app.state.builds)

    listing = client.get("/api/builds", params={"project": "demo"}).json()
    assert [row["id"] for row in listing["builds"]][:2] == [second, first]
    assert {kind["id"] for kind in listing["kinds"]} == set(builds.KINDS)

    assert client.delete(f"/api/builds/{first}").status_code == 204
    assert client.get(f"/api/builds/{first}").status_code == 404


def test_history_survives_a_restart(tmp_path, monkeypatch):
    """A build finished before a restart is still on the list afterwards."""
    project = make_project(tmp_path)
    fake = make_fake_flutter(tmp_path / "bin")
    monkeypatch.setattr(flutter, "resolve", lambda c, p: str(fake))
    data_dir = tmp_path / "data"

    app = create_app(data_dir=data_dir)
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        client.post("/api/projects", json={"name": "demo", "path": str(project)})
        build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
        wait_for(build_id, app.state.builds)

    app2 = create_app(data_dir=data_dir)
    with TestClient(app2) as client:
        client.post("/api/auth/login", json={"password": PASSWORD})
        rows = client.get("/api/builds").json()["builds"]
        assert [row["id"] for row in rows] == [build_id]
        assert rows[0]["artifact_name"] == "app-debug.apk"


# --- installing a build onto a device ---------------------------------------
# This is the join between the two halves of the product, so the interesting
# cases are the refusals: the wrong kind of artifact, a device that is not
# there, and a build that has not finished.

def _make_build(client, kind="apk-debug") -> str:
    build_id = client.post("/api/projects/demo/builds", json={"kind": kind}).json()["id"]
    wait_for(build_id, client.app.state.builds)
    return build_id


def _register_device(client, alias="phone", **extra):
    client.app.state.store.upsert_device(alias, {"type": "usb", "serial": "SERIAL", **extra})


def test_install_pushes_the_artifact_to_the_device(client, monkeypatch):
    _register_device(client)
    monkeypatch.setattr(builds_module.devices, "resolve_serial", lambda store, alias, connected=None: "SERIAL")
    installed = {}
    monkeypatch.setattr(
        builds_module.toolbox, "install_apk",
        lambda serial, path: installed.update(serial=serial, path=path) or (True, "Success"),
    )

    build_id = _make_build(client)
    response = client.post(f"/api/builds/{build_id}/install", json={"device": "phone"})

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert installed["serial"] == "SERIAL"
    # The file handed to adb is the copy kept in the data directory, not the one
    # in Flutter's build/ folder, which a later clean would remove.
    assert installed["path"].endswith("app-debug.apk")
    assert "outputs" not in installed["path"]


def test_an_aab_is_refused_with_the_reason(client, monkeypatch):
    """An AAB is a Play upload; failing with an archive error would be useless."""
    _register_device(client)
    monkeypatch.setattr(builds_module.devices, "resolve_serial", lambda store, alias, connected=None: "SERIAL")

    build_id = _make_build(client, kind="aab-release")
    response = client.post(f"/api/builds/{build_id}/install", json={"device": "phone"})

    assert response.status_code == 409
    assert "Play" in response.json()["detail"]


def test_install_reports_a_device_that_is_not_connected(client, monkeypatch):
    _register_device(client)
    monkeypatch.setattr(builds_module.devices, "resolve_serial", lambda store, alias, connected=None: None)

    build_id = _make_build(client)
    response = client.post(f"/api/builds/{build_id}/install", json={"device": "phone"})

    assert response.status_code == 409
    assert "not connected" in response.json()["detail"]


def test_install_rejects_an_unknown_device(client):
    build_id = _make_build(client)

    assert client.post(f"/api/builds/{build_id}/install", json={"device": "nope"}).status_code == 404


def test_install_rejects_a_build_that_has_not_finished(client, monkeypatch):
    """A build still running has no artifact to push yet."""
    _register_device(client)
    # A build that takes a moment, so there is a running window to test.
    slower = make_fake_flutter(client.project.parent / "slow-bin", sleep=3)
    monkeypatch.setattr(flutter, "resolve", lambda c, p: str(slower))

    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]
    assert client.app.state.builds.row(build_id)["status"] == "running"

    response = client.post(f"/api/builds/{build_id}/install", json={"device": "phone"})

    assert response.status_code == 409
    assert "not finished" in response.json()["detail"]


def test_install_reports_a_device_that_refuses(client, monkeypatch):
    _register_device(client)
    monkeypatch.setattr(builds_module.devices, "resolve_serial", lambda store, alias, connected=None: "SERIAL")
    monkeypatch.setattr(builds_module.toolbox, "install_apk", lambda serial, path: (False, "INSTALL_FAILED_INSUFFICIENT_STORAGE"))

    build_id = _make_build(client)
    response = client.post(f"/api/builds/{build_id}/install", json={"device": "phone"})

    assert response.status_code == 502
    assert "INSUFFICIENT_STORAGE" in response.json()["detail"]
