"""Fenox — a single-user, self-hosted web app for Android devices and Flutter.

`core` is the engine, `server` is the hub, and `cli` is the management surface.
Neither the server nor the CLI imports the other; both build on `core`.
"""

from .version import __version__

__all__ = ["__version__"]
