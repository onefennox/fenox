import struct

from fenox.core import mirror


def test_server_argv_uses_the_1x_argument_order():
    argv = mirror.server_argv("1.25", max_size=1024, bit_rate=4_000_000, max_fps=30)
    assert argv[:3] == ["shell", "CLASSPATH=/data/local/tmp/scrcpy-server.jar", "app_process"]
    assert argv[3:6] == ["/", "com.genymobile.scrcpy.Server", "1.25"]
    # version, log level, size, bitrate, fps, orientation, tunnel, crop, frame meta, control
    assert argv[6:] == ["info", "1024", "4000000", "30", "-1", "false", "-", "true", "false"]


def test_parse_codec_meta_reads_codec_and_size():
    data = struct.pack(">4sII", b"h264", 1080, 1920)
    assert mirror.parse_codec_meta(data) == {"codec": "h264", "width": 1080, "height": 1920}


def test_available_reports_missing_scrcpy(monkeypatch):
    monkeypatch.setattr(mirror, "scrcpy_binary", lambda: None)
    ok, reason = mirror.available()
    assert ok is False
    assert "not installed" in reason


def test_available_reports_missing_server_jar(monkeypatch):
    monkeypatch.setattr(mirror, "scrcpy_binary", lambda: "/usr/bin/scrcpy")
    monkeypatch.setattr(mirror, "scrcpy_version", lambda: "1.25")
    monkeypatch.setattr(mirror, "server_path", lambda: None)
    ok, reason = mirror.available()
    assert ok is False
    assert "jar" in reason


def test_mirror_status_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fenox.server.app import create_app

    monkeypatch.setattr(mirror, "scrcpy_binary", lambda: "/usr/bin/scrcpy")
    monkeypatch.setattr(mirror, "scrcpy_version", lambda: "1.25")
    monkeypatch.setattr(mirror, "server_path", lambda: "/usr/share/scrcpy/scrcpy-server")

    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": "a-strong-owner-password"})
        body = client.get("/api/devices/phone/mirror/status").json()
        assert body["available"] is True
        assert body["version"] == "1.25"
        assert body["active"] is False
