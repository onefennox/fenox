from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fenox.core import host
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def _flutter_app(parent: Path, name: str) -> Path:
    app = parent / name
    (app / "android").mkdir(parents=True)
    (app / "pubspec.yaml").write_text("name: x\n")
    return app


def test_browse_lists_only_directories(tmp_path):
    root = tmp_path / "root"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir()
    (root / "notes.txt").write_text("x")

    listing = host.browse_dirs(str(root))

    assert [entry["name"] for entry in listing["dirs"]] == ["alpha", "beta"]
    assert listing["path"] == str(root)
    assert listing["parent"] == str(tmp_path)


def test_browse_marks_flutter_project_roots(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _flutter_app(root, "app")
    (root / "docs").mkdir()

    listing = host.browse_dirs(str(root))
    by_name = {entry["name"]: entry for entry in listing["dirs"]}

    assert by_name["app"]["flutter"] is True
    assert by_name["docs"]["flutter"] is False
    assert listing["flutter"] is False
    # A Flutter root reports itself, so the picker can label the current folder.
    assert host.browse_dirs(str(root / "app"))["flutter"] is True


def test_browse_skips_noise_and_hidden_entries(tmp_path):
    root = tmp_path / "root"
    for name in ("node_modules", ".git", ".hidden", ".dart_tool"):
        (root / name).mkdir(parents=True)
    (root / "keep").mkdir()

    assert [entry["name"] for entry in host.browse_dirs(str(root))["dirs"]] == ["keep"]


def test_browse_defaults_to_home_and_expands_tilde(tmp_path, monkeypatch):
    home = tmp_path / "fakehome"
    (home / "work").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    assert host.browse_dirs()["path"] == str(home)
    assert host.browse_dirs("~")["path"] == str(home)
    assert host.browse_dirs("~/work")["path"] == str(home / "work")


def test_browse_recovers_from_a_stale_path(tmp_path):
    """A bookmark to something that moved should land somewhere usable."""
    listing = host.browse_dirs(str(tmp_path / "gone" / "deeper"))

    assert Path(listing["path"]).is_dir()
    assert listing["path"].startswith(str(tmp_path))


def test_browse_rejects_a_file(tmp_path):
    target = tmp_path / "pubspec.yaml"
    target.write_text("name: x\n")

    with pytest.raises(NotADirectoryError):
        host.browse_dirs(str(target))


def test_browse_offers_quick_entries(tmp_path, monkeypatch):
    home = tmp_path / "fakehome"
    (home / "Projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    quick = {entry["label"] for entry in host.browse_dirs()["quick"]}

    assert {"Home", "Projects"} <= quick
    assert {entry["path"] for entry in host.browse_dirs()["quick"] if entry["label"] == "Home"} == {str(home)}


def test_quick_entries_omit_directories_that_do_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

    assert "Projects" not in {entry["label"] for entry in host.browse_dirs()["quick"]}


def _client(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_browse_route_requires_authentication(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    try:
        assert client.get("/api/system/browse").status_code in (401, 403)
    finally:
        client.__exit__(None, None, None)


def test_browse_route_returns_a_listing(tmp_path):
    root = tmp_path / "root"
    (root / "alpha").mkdir(parents=True)
    client = _client(tmp_path)
    try:
        body = client.get("/api/system/browse", params={"path": str(root)}).json()
        assert body["path"] == str(root)
        assert [entry["name"] for entry in body["dirs"]] == ["alpha"]
        assert body["quick"]
    finally:
        client.__exit__(None, None, None)


def test_browse_route_rejects_a_file_with_400(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("x")
    client = _client(tmp_path)
    try:
        assert client.get("/api/system/browse", params={"path": str(target)}).status_code == 400
    finally:
        client.__exit__(None, None, None)


def test_projects_dir_is_settable_from_settings(tmp_path):
    client = _client(tmp_path)
    try:
        assert client.get("/api/settings").json()["projects_dir"] == ""
        updated = client.patch("/api/settings", json={"projects_dir": str(tmp_path)}).json()
        assert updated["projects_dir"] == str(tmp_path)
    finally:
        client.__exit__(None, None, None)


def test_scan_accepts_an_explicit_path(tmp_path):
    root = tmp_path / "root"
    project = _flutter_app(root, "mobile-app")
    client = _client(tmp_path)
    try:
        body = client.post("/api/projects/scan", json={"path": str(root)}).json()
        assert body["added"] == ["mobile-app"]
        assert client.get("/api/projects").json()["projects"]["mobile-app"]["path"] == str(project)
    finally:
        client.__exit__(None, None, None)


def test_browse_suggests_a_name_only_for_flutter_roots(tmp_path):
    root = tmp_path / "root"
    app = _flutter_app(root, "mobile-app")
    client = _client(tmp_path)
    try:
        # A plain folder has nothing to suggest.
        assert "suggested_name" not in client.get("/api/system/browse", params={"path": str(root)}).json()
        # A Flutter app root prefills the add-project form.
        body = client.get("/api/system/browse", params={"path": str(app)}).json()
        assert body["flutter"] is True
        assert body["suggested_name"] == "mobile-app"
    finally:
        client.__exit__(None, None, None)
