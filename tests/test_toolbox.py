from fastapi.testclient import TestClient

from fenox.core import devices, toolbox
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def _client(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_actions_require_an_online_device(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "live_serial", lambda store, alias, connected=None: None)
    client = _client(tmp_path)
    try:
        assert client.post("/api/devices/phone/wake").status_code == 409
        assert client.get("/api/devices/phone/apps").status_code == 409
        assert client.get("/api/devices/phone/phone/contacts").status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_input_and_app_actions(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(devices, "live_serial", lambda store, alias, connected=None: "SERIAL")
    monkeypatch.setattr(toolbox, "tap", lambda s, x, y: (calls.append(("tap", x, y)) or (True, "")))
    monkeypatch.setattr(toolbox, "list_packages", lambda s, third_party=True: ["com.example.demo"])

    client = _client(tmp_path)
    try:
        assert client.post("/api/devices/phone/input", json={"type": "tap", "x": 10, "y": 20}).status_code == 200
        assert calls == [("tap", 10, 20)]
        assert client.get("/api/devices/phone/apps").json()["apps"] == ["com.example.demo"]
        assert client.post("/api/devices/phone/input", json={"type": "nonsense"}).status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_device_info_reports_props_battery_and_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "live_serial", lambda store, alias, connected=None: "SERIAL")
    monkeypatch.setattr(toolbox, "device_props", lambda s: {"model": "Pixel 7"})
    monkeypatch.setattr(toolbox, "battery", lambda s: {"level": "88"})
    monkeypatch.setattr(toolbox, "storage", lambda s: "Filesystem  Size")

    client = _client(tmp_path)
    try:
        body = client.get("/api/devices/phone/info").json()
        assert body["props"]["model"] == "Pixel 7"
        assert body["battery"]["level"] == "88"
        assert "Filesystem" in body["storage"]
    finally:
        client.__exit__(None, None, None)
