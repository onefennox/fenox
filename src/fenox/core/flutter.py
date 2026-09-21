"""Flutter command construction and tool discovery.

The flutter binary is resolved through `host`, which checks a configured path
first, then PATH, then the usual install locations. The supervisor owns the
process; this module only decides *what* to run.
"""
from __future__ import annotations

import os

from . import host


def resolve(configured: str | None = None, project: str | None = None) -> str | None:
    """The flutter binary to use: a project's FVM SDK, an explicit setting, or a
    discovered install."""
    return host.find_flutter(configured, project)


def which_flutter(configured: str | None = None, project: str | None = None) -> str | None:
    return resolve(configured, project)


def run_argv(flutter: str, entry: dict, serial: str, mode: str) -> list[str]:
    """The `flutter run` command line for one project on one device.

    Local mode injects the local API (and websocket) URLs; remote mode injects
    the remote ones. The supervisor appends `--pid-file` so it can signal reload
    and restart without scraping the terminal.
    """
    argv = [flutter, "run", "-d", serial]
    if mode == "remote":
        api = str(entry.get("api_remote") or "").strip() or str(entry.get("api_local") or "")
        socket = str(entry.get("socket_remote") or "").strip()
    else:
        api = str(entry.get("api_local") or "").strip()
        socket = str(entry.get("socket_local") or "").strip()
    if api:
        argv.append(f"--dart-define=API_BASE_URL={api}")
    if socket:
        argv.append(f"--dart-define=SOCKET_BASE_URL={socket}")
    return argv


def build_argv(flutter: str, entry: dict) -> list[str]:
    remote_api = str(entry.get("api_remote") or "").strip()
    argv = [flutter, "build", "apk", "--release", f"--dart-define=API_BASE_URL={remote_api}"]
    if entry.get("socket_remote"):
        argv.append(f"--dart-define=SOCKET_BASE_URL={entry['socket_remote']}")
    return argv


def preflight(flutter: str | None, entry: dict) -> list[str]:
    """Problems that would stop a run before we even try."""
    issues = []
    if not flutter:
        issues.append("the flutter SDK was not found; set it in Settings or install it and re-check")
    path = os.path.expanduser(str(entry.get("path") or ""))
    if not os.path.isdir(path):
        issues.append(f"project directory not found: {path}")
    return issues
