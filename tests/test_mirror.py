import struct

from fenox.core import host, mirror


def test_server_args_match_the_server_contract():
    args = mirror.server_args("3.3.3")
    # The first argument must be the exact server version.
    assert args[0] == "3.3.3"
    # video only, no control channel, and the jar must not self-delete.
    assert "audio=false" in args
    assert "control=false" in args
    assert "cleanup=false" in args


def test_parse_codec_meta_reads_codec_and_size():
    data = struct.pack(">4sII", b"h264", 1080, 1920)
    assert mirror.parse_codec_meta(data) == {"codec": "h264", "width": 1080, "height": 1920}


def test_available_requires_adb(monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: None)
    ok, reason = mirror.available()
    assert ok is False
    assert "adb" in reason


def test_available_rejects_a_missing_override(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: "/usr/bin/adb")
    monkeypatch.setenv("FENOX_SCRCPY_SERVER", str(tmp_path / "nope"))
    ok, reason = mirror.available()
    assert ok is False
    assert "missing" in reason


def test_available_when_adb_is_present(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "adb_client", lambda configured=None: "/usr/bin/adb")
    monkeypatch.delenv("FENOX_SCRCPY_SERVER", raising=False)
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
        assert body["active"] is False
