
import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep tests away from the developer's real home and data directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FENOX_DATA_DIR", raising=False)
    # No background USB/mDNS probing unless a test opts in.
    monkeypatch.setenv("FENOX_NO_AUTODETECT", "1")
    yield home
