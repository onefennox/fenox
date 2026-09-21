from fenox.core import host, mirror


def test_server_args_request_a_raw_stream():
    args = mirror.server_args("3.3.3")
    assert args[0] == "3.3.3"
    assert "raw_stream=true" in args
    assert "audio=false" in args
    assert "control=false" in args
    assert "cleanup=false" in args


def test_path_for_sanitises_ids():
    assert mirror.path_for("s21+usb") == "device_s21_usb"
    assert mirror.path_for("192.168.1.9:5555") == "device_192_168_1_9_5555"


def test_codec_string_reads_the_sps():
    # SPS NAL: start code, 0x67 (type 7), profile 0x64, constraints 0x00, level 0x33
    stream = b"\x00\x00\x00\x01\x67\x64\x00\x33\xac\xb4\x02"
    assert mirror.codec_string(stream) == "avc1.640033"


def test_codec_string_falls_back_when_there_is_no_sps():
    assert mirror.codec_string(b"\x00\x00\x00\x01\x41\x00") == "avc1.42E01E"


def test_available_requires_adb(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: None)
    ok, reason = mirror.available()
    assert ok is False and "adb" in reason


def test_available_requires_ffmpeg(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: "/usr/bin/adb")
    monkeypatch.setattr(mirror.shutil, "which", lambda name: None if name == "ffmpeg" else "/usr/bin/" + name)
    ok, reason = mirror.available()
    assert ok is False and "ffmpeg" in reason


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
        assert body["active"] is False
