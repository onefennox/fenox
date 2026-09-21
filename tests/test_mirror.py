from fenox.core import host, mediamtx, mirror


def test_server_args_request_a_raw_stream():
    args = mirror.server_args("3.3.3")
    # The first argument must be the exact server version.
    assert args[0] == "3.3.3"
    # Raw H.264 for ffmpeg, no audio or control channel, and no self-delete.
    assert "raw_stream=true" in args
    assert "audio=false" in args
    assert "control=false" in args
    assert "cleanup=false" in args


def test_path_for_sanitises_ids():
    assert mirror.path_for("s21+usb") == "device_s21_usb"
    assert mirror.path_for("192.168.1.9:5555") == "device_192_168_1_9_5555"


def test_available_requires_adb(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: None)
    ok, reason = mirror.available()
    assert ok is False
    assert "adb" in reason


def test_available_requires_ffmpeg(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: "/usr/bin/adb")
    monkeypatch.setattr(mediamtx, "ffmpeg_binary", lambda: None)
    ok, reason = mirror.available()
    assert ok is False
    assert "ffmpeg" in reason


def test_available_when_ready(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: "/usr/bin/adb")
    monkeypatch.setattr(mediamtx, "ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    monkeypatch.delenv("FENOX_MEDIAMTX", raising=False)
    ok, reason = mirror.available()
    assert ok is True and reason == ""


def test_mirror_status_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fenox.core import scrcpy_server
    from fenox.server.app import create_app

    monkeypatch.setattr(mirror, "available", lambda cache_dir=None: (True, ""))
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": "a-strong-owner-password"})
        body = client.get("/api/devices/phone/mirror/status").json()
        assert body["available"] is True
        assert body["server_version"] == scrcpy_server.PINNED_VERSION
        assert body["mediamtx_version"] == mediamtx.PINNED_VERSION
        assert body["active"] is False
