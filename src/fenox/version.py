"""Version identity.

Installed (pip) -> the distribution version. Running from a source checkout ->
the `VERSION` file. Kept in one place so the CLI, the hub, and the release tooling
all agree.
"""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version() -> str:
    try:
        return version("fenox")
    except PackageNotFoundError:
        pass
    candidate = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return candidate.read_text().strip()
    except OSError:
        return "0.0.0"


__version__ = _version()
