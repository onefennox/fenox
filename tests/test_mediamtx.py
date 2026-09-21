from fenox.core import mediamtx


def test_binary_path_is_versioned_and_arch_specific(tmp_path):
    path = mediamtx.binary_path(tmp_path, "1.21.1")
    assert path.name == "mediamtx"
    assert "v1.21.1" in path.parent.name


def test_cached_reflects_an_executable_binary(tmp_path):
    assert mediamtx.cached(tmp_path, "1.21.1") is False
    binary = mediamtx.binary_path(tmp_path, "1.21.1")
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)
    assert mediamtx.cached(tmp_path, "1.21.1") is True
    binary.chmod(0o644)
    assert mediamtx.cached(tmp_path, "1.21.1") is False


def test_ensure_prefers_an_override(tmp_path, monkeypatch):
    override = tmp_path / "mediamtx"
    override.write_bytes(b"#!/bin/sh\n")
    override.chmod(0o755)
    monkeypatch.setenv("FENOX_MEDIAMTX", str(override))
    assert mediamtx.ensure(tmp_path) == override


def test_config_enables_webrtc_and_rtsp(tmp_path):
    path = mediamtx.write_config(tmp_path)
    text = path.read_text()
    assert "rtsp: yes" in text
    assert "webrtc: yes" in text
    assert mediamtx.WEBRTC_ADDRESS in text
    assert "all_others:" in text
