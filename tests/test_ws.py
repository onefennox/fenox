import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fenox.core import adb
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def test_events_stream_devices_to_an_authenticated_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "connected_ids", lambda: [])
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": PASSWORD})
        with client.websocket_connect("/ws/events") as ws:
            message = ws.receive_json()
            assert message["type"] == "devices"
            assert message["devices"] == []


def test_events_reject_an_unauthenticated_client(tmp_path):
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/events") as ws:
                ws.receive_json()
