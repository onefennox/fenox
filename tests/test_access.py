from fastapi.testclient import TestClient

from fenox.core import access, doctor
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def _client(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_bind_host_by_reach():
    assert access.bind_host("local") == "127.0.0.1"
    assert access.bind_host("lan") == "0.0.0.0"
    assert access.bind_host("remote") == "127.0.0.1"


def test_settings_reach_change_requires_restart(tmp_path):
    client = _client(tmp_path)
    try:
        initial = client.get("/api/settings").json()
        assert initial["reach"] == "local"
        assert initial["restart_required"] is False

        updated = client.patch("/api/settings", json={"reach": "lan"}).json()
        assert updated["reach"] == "lan"
        assert updated["restart_required"] is True
        assert "0.0.0.0" not in updated["urls"][0]

        assert client.patch("/api/settings", json={"reach": "nonsense"}).status_code == 422
        assert client.patch("/api/settings", json={"port": 70000}).status_code == 422

        # A domain-only change does not need a restart.
        only_domain = client.patch("/api/settings", json={"remote_domain": "example.test"}).json()
        assert only_domain["restart_required"] is True  # reach already changed above
    finally:
        client.__exit__(None, None, None)


def test_token_rotation_changes_the_token(tmp_path):
    client = _client(tmp_path)
    try:
        before = client.get("/api/settings").json()["token"]
        after = client.post("/api/settings/token").json()["token"]
        assert before and after and before != after
    finally:
        client.__exit__(None, None, None)


def test_doctor_reports_tools_and_plans():
    report = doctor.checks()
    names = {tool["name"] for tool in report["tools"]}
    assert {"adb", "scrcpy", "flutter", "tmux"} <= names

    tmux = doctor.install_plan("tmux")
    assert tmux["requires_sudo"] is True
    assert "apt-get install -y tmux" in tmux["command"]

    flutter = doctor.install_plan("flutter")
    assert flutter["requires_sudo"] is False
    assert "flutter.dev" in flutter["manual"]


def test_doctor_route_and_install_refuses_sudo(tmp_path):
    client = _client(tmp_path)
    try:
        report = client.get("/api/system/doctor").json()
        assert "tools" in report

        result = client.post("/api/system/install", json={"tool": "tmux"}).json()
        assert result["requires_sudo"] is True
        assert result["command"].startswith("sudo apt-get")
        assert client.post("/api/system/install", json={"tool": "nope"}).status_code == 404
    finally:
        client.__exit__(None, None, None)
