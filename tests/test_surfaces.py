"""Activity, project files, and captures.

These three all reach beyond the device — into the database, the project
directory and the output folders — so the interesting cases are the refusals:
where a path must not be followed, and where a listing must not be trusted.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fenox.core import host, projects
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def make_project(root: Path, name: str = "demo") -> Path:
    project = root / name
    (project / "lib").mkdir(parents=True)
    (project / "android").mkdir()
    (project / "pubspec.yaml").write_text("name: demo\n")
    (project / "lib" / "main.dart").write_text("void main() {}\n")
    (project / "build").mkdir()  # noise, must not be listed
    (project / "build" / "junk.txt").write_text("noise\n")
    (project / ".git").mkdir()
    return project


@pytest.fixture
def client(tmp_path):
    project = make_project(tmp_path)
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        client.post("/api/projects", json={"name": "demo", "path": str(project)})
        client.project = project  # type: ignore[attr-defined]
        yield client


# --- project files ----------------------------------------------------------

def test_tree_lists_the_project_without_the_noise(client):
    tree = client.get("/api/projects/demo/tree").json()

    names = {entry["name"] for entry in tree["entries"]}
    assert "pubspec.yaml" in names
    assert "lib" in names
    # build/, .git/ and dotfiles are working space, not project content.
    assert "build" not in names
    assert ".git" not in names


def test_tree_descends_and_reads_a_file(client):
    tree = client.get("/api/projects/demo/tree", params={"path": "lib"}).json()
    assert [entry["name"] for entry in tree["entries"]] == ["main.dart"]

    text = client.get("/api/projects/demo/file", params={"path": "lib/main.dart"}).json()["text"]
    assert "void main()" in text


def test_tree_refuses_to_leave_the_project(client):
    """The server serves the owner's filesystem, so `..` must not resolve."""
    for escape in ("../../etc/passwd", "..", "/etc/passwd"):
        response = client.get("/api/projects/demo/tree", params={"path": escape})
        assert response.status_code == 400, escape


def test_reading_a_file_refuses_to_leave_the_project(client):
    assert client.get("/api/projects/demo/file", params={"path": "../../etc/passwd"}).status_code == 400


def test_reading_a_directory_is_refused(client):
    assert client.get("/api/projects/demo/file", params={"path": "lib"}).status_code == 400


def test_binary_and_oversized_files_are_refused(client):
    (client.project / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    assert client.get("/api/projects/demo/file", params={"path": "blob.bin"}).status_code == 400

    (client.project / "big.txt").write_text("x" * (projects._MAX_PREVIEW + 10))
    assert client.get("/api/projects/demo/file", params={"path": "big.txt"}).status_code == 400


def test_tree_for_an_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/tree").status_code == 404


# --- captures ---------------------------------------------------------------

def test_captures_lists_and_downloads(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    shots = host.output_dirs()["screenshot"]
    shots.mkdir(parents=True, exist_ok=True)
    (shots / "shot.png").write_bytes(b"\x89PNG data")

    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        listing = client.get("/api/system/captures").json()
        assert "shot.png" in {row["name"] for row in listing["captures"]}
        assert listing["directory"]

        download = client.get("/api/system/captures/download", params={"path": str(shots / "shot.png")})
        assert download.status_code == 200
        assert download.content == b"\x89PNG data"

        # This route takes a filesystem path, so it has to refuse anything
        # outside the folders Fenox owns.
        assert client.get("/api/system/captures/download", params={"path": "/etc/passwd"}).status_code == 403

    (shots / "shot.png").unlink(missing_ok=True)


def test_captures_requires_authentication(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        client.post("/api/auth/logout")
        assert client.get("/api/system/captures").status_code in (401, 403)


# --- activity ---------------------------------------------------------------

def test_activity_lists_devices_even_when_nothing_has_happened(client):
    feed = client.get("/api/activity").json()

    assert feed["items"] == []
    # Device state is not an event, so it comes back separately rather than
    # being given a fake timestamp to sort against builds and runs.
    assert isinstance(feed["devices"], list)


def test_activity_includes_builds(client, tmp_path, monkeypatch):
    """A finished build should show up without visiting the builds page."""
    from fenox.core import flutter

    fake = tmp_path / "fake-flutter"
    fake.write_text(
        "#!/bin/sh\n"
        "mkdir -p build/app/outputs/flutter-apk\n"
        "printf x > build/app/outputs/flutter-apk/app-debug.apk\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(flutter, "resolve", lambda configured, project_path: str(fake))

    build_id = client.post("/api/projects/demo/builds", json={"kind": "apk-debug"}).json()["id"]

    import time

    for _ in range(200):
        row = client.app.state.builds.row(build_id)
        if row and row["status"] != "running":
            break
        time.sleep(0.05)

    items = client.get("/api/activity").json()["items"]
    assert any(item["kind"] == "build" and item["id"] == build_id for item in items)


def test_activity_requires_authentication(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        client.post("/api/auth/logout")
        assert client.get("/api/activity").status_code in (401, 403)
