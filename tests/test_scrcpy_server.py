import pytest

from fenox.core import scrcpy_server


def test_cache_path_includes_the_version(tmp_path):
    path = scrcpy_server.cache_path(tmp_path, "3.3.3")
    assert path.name == "scrcpy-server-v3.3.3"
    assert path.parent.name == "scrcpy"


def test_cached_reflects_file_presence(tmp_path):
    assert scrcpy_server.cached(tmp_path, "3.3.3") is False
    target = scrcpy_server.cache_path(tmp_path, "3.3.3")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * (scrcpy_server._MIN_SIZE + 1))
    assert scrcpy_server.cached(tmp_path, "3.3.3") is True


def test_ensure_prefers_an_explicit_override(tmp_path, monkeypatch):
    override = tmp_path / "my-server"
    override.write_bytes(b"server")
    monkeypatch.setenv("FENOX_SCRCPY_SERVER", str(override))
    assert scrcpy_server.ensure(tmp_path) == override


def test_ensure_uses_the_cache_without_downloading(tmp_path, monkeypatch):
    monkeypatch.delenv("FENOX_SCRCPY_SERVER", raising=False)
    target = scrcpy_server.cache_path(tmp_path, scrcpy_server.PINNED_VERSION)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * (scrcpy_server._MIN_SIZE + 1))

    def boom(*_args, **_kwargs):
        raise AssertionError("download should not run when the server is cached")

    monkeypatch.setattr(scrcpy_server, "download", boom)
    assert scrcpy_server.ensure(tmp_path) == target


def test_ensure_downloads_and_caches(tmp_path, monkeypatch):
    monkeypatch.delenv("FENOX_SCRCPY_SERVER", raising=False)
    monkeypatch.setattr(scrcpy_server, "download", lambda version, timeout=60: b"y" * (scrcpy_server._MIN_SIZE + 1))
    path = scrcpy_server.ensure(tmp_path, "3.3.3")
    assert path.is_file()
    assert path.stat().st_size > scrcpy_server._MIN_SIZE


def test_download_rejects_a_too_small_file(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"tiny"

    monkeypatch.setattr(scrcpy_server.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(scrcpy_server.ProvisionError):
        scrcpy_server.download("3.3.3")
