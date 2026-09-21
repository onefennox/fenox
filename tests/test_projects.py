from pathlib import Path

from fastapi.testclient import TestClient

from fenox.core import projects
from fenox.core.config import Store
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def _flutter_project(base: Path, name: str = "demo") -> Path:
    project = base / name
    (project / "android" / "app").mkdir(parents=True)
    (project / "pubspec.yaml").write_text(f"name: {name}\n")
    (project / "android" / "app" / "build.gradle").write_text('applicationId "com.example.demo"\n')
    (project / "lib").mkdir()
    return project


def test_build_entry_detects_port_backend_and_package(tmp_path):
    project = _flutter_project(tmp_path)
    backend = tmp_path / "demo_backend"
    backend.mkdir()
    (backend / "package.json").write_text('{"scripts": {"dev": "node server.js"}}')
    (backend / ".env").write_text("PORT=4321\n")

    entry = projects.build_entry("demo", str(project), {})
    assert entry["port"] == "4321"
    assert entry["api_local"] == "http://localhost:4321/api"
    assert entry["package"] == "com.example.demo"
    assert entry["backend"]["path"] == str(backend)
    assert entry["backend"]["cmd"]


def test_scan_registers_new_projects(tmp_path):
    _flutter_project(tmp_path, "alpha")
    _flutter_project(tmp_path, "beta")
    store = Store(tmp_path / "data").load()

    found = projects.scan(store, str(tmp_path))
    names = sorted(name for name, _ in found)
    assert names == ["alpha", "beta"]
    assert set(store.projects()) == {"alpha", "beta"}
    # A second scan finds nothing new.
    assert projects.scan(store, str(tmp_path)) == []


def _client(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_project_routes_crud_and_scan(tmp_path):
    project = _flutter_project(tmp_path, "demo")
    client = _client(tmp_path)
    try:
        created = client.post("/api/projects", json={"name": "demo", "path": str(project)})
        assert created.status_code == 201
        assert created.json()["project"]["package"] == "com.example.demo"

        assert client.post("/api/projects", json={"name": "demo", "path": str(project)}).status_code == 409
        assert set(client.get("/api/projects").json()["projects"]) == {"demo"}

        patched = client.patch("/api/projects/demo", json={"port": "9999"}).json()
        assert patched["project"]["port"] == "9999"

        assert client.delete("/api/projects/demo").status_code == 204
        assert client.get("/api/projects/demo").status_code == 404

        client.app.state.store.settings["projects_dir"] = str(tmp_path)
        scanned = client.post("/api/projects/scan").json()
        assert "demo" in scanned["added"]
    finally:
        client.__exit__(None, None, None)
