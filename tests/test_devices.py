from fastapi.testclient import TestClient

from fenox.core import adb, devices
from fenox.core.config import Store
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


# --- engine ---------------------------------------------------------------

def test_autodetect_registers_a_usb_phone(tmp_path, monkeypatch):
    monkeypatch.delenv("FENOX_NO_AUTODETECT")
    monkeypatch.setattr(adb, "connected_ids", lambda: ["R58M12345"])
    monkeypatch.setattr(adb, "getprop", lambda serial, prop, timeout=4: "Pixel 7a")

    store = Store(tmp_path).load()
    assert devices.autodetect(store) == ["pixel7a"]
    assert store.device("pixel7a") == {"type": "usb", "serial": "R58M12345", "model": "Pixel 7a"}
    # A second pass does not duplicate it.
    assert devices.autodetect(store) == []


def test_live_serial_matches_by_type(tmp_path, monkeypatch):
    store = Store(tmp_path).load()
    store.upsert_device("phone", {"type": "usb", "serial": "ABC"})
    store.upsert_device("wifi", {"type": "wireless", "ip": "10.0.0.5", "port": "5555"})

    monkeypatch.setattr(adb, "connected_ids", lambda: ["ABC", "10.0.0.5:6000"])
    assert devices.live_serial(store, "phone") == "ABC"
    assert devices.live_serial(store, "wifi") == "10.0.0.5:6000"


def test_resolve_wireless_refreshes_the_port(tmp_path, monkeypatch):
    store = Store(tmp_path).load()
    store.upsert_device("wifi", {"type": "wireless", "ip": "10.0.0.5", "port": "5555"})

    connected: list[str] = []
    monkeypatch.setattr(adb, "connected_ids", lambda: list(connected))
    monkeypatch.setattr(adb, "mdns_port", lambda ip: "6100")

    def fake_connect(ip, port):
        connected.append(f"{ip}:{port}")
        return True, "connected"

    monkeypatch.setattr(adb, "connect", fake_connect)
    assert devices.resolve_serial(store, "wifi") == "10.0.0.5:6100"
    assert store.device("wifi")["port"] == "6100"


def test_pending_devices_are_reported(monkeypatch):
    monkeypatch.setattr(
        adb,
        "devices_output",
        lambda: "List of devices attached\nR58\toffline\nOK\tdevice\n",
    )
    assert adb.pending_devices() == [("R58", "offline")]


# --- HTTP -----------------------------------------------------------------

def _client(tmp_path) -> TestClient:
    app = create_app(data_dir=tmp_path)
    client = TestClient(app)
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_device_routes_list_update_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "connected_ids", lambda: ["ABC"])
    client = _client(tmp_path)
    try:
        store = client.app.state.store
        store.upsert_device("phone", {"type": "usb", "serial": "ABC", "model": "Pixel 7"})

        listed = client.get("/api/devices").json()["devices"]
        assert listed[0]["id"] == "phone" and listed[0]["online"] is True

        renamed = client.patch("/api/devices/phone", json={"name": "myphone"}).json()
        assert renamed["id"] == "myphone"
        assert store.device("phone") is None
        assert store.device("myphone")["serial"] == "ABC"

        assert client.patch("/api/devices/myphone", json={"disabled": True}).json()["disabled"] is True
        assert client.delete("/api/devices/myphone").status_code == 204
        assert client.get("/api/devices/myphone").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_connect_reports_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "connected_ids", lambda: [])
    monkeypatch.setattr(adb, "mdns_port", lambda ip: None)
    client = _client(tmp_path)
    try:
        client.app.state.store.upsert_device("phone", {"type": "usb", "serial": "ABC"})
        assert client.post("/api/devices/phone/connect").status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_discover_runs_only_the_requested_transport(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(devices, "autodetect", lambda store: calls.append("usb") or [])
    monkeypatch.setattr(devices, "autodetect_wireless", lambda store, force=False: (calls.append("wireless"), ([], []))[1])
    client = _client(tmp_path)
    try:
        client.post("/api/devices/discover?mode=usb")
        assert calls == ["usb"]
        calls.clear()
        client.post("/api/devices/discover?mode=wireless")
        assert calls == ["wireless"]
        calls.clear()
        client.post("/api/devices/discover?mode=all")
        assert set(calls) == {"usb", "wireless"}
        assert client.post("/api/devices/discover?mode=nonsense").status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_connect_wireless_registers_the_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "connect", lambda ip, port: (True, "connected"))
    monkeypatch.setattr(adb, "getprop", lambda serial, prop, timeout=4: "Pixel 7")
    monkeypatch.setattr(adb, "connected_ids", lambda: ["192.168.1.20:37001"])
    client = _client(tmp_path)
    try:
        device = client.post("/api/devices/connect-wireless", json={"ip": "192.168.1.20", "port": "37001"}).json()
        assert device["id"] == "pixel7"
        assert device["type"] == "wireless"
        assert device["online"] is True
        assert client.app.state.store.device("pixel7")["ip"] == "192.168.1.20"

        monkeypatch.setattr(adb, "connect", lambda ip, port: (False, "failed to connect"))
        assert client.post("/api/devices/connect-wireless", json={"ip": "10.0.0.9", "port": "5"}).status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_empty_registry_lists_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "connected_ids", lambda: [])
    client = _client(tmp_path)
    try:
        assert client.get("/api/devices").json()["devices"] == []
    finally:
        client.__exit__(None, None, None)
