"""Flutter command construction and tool discovery.

The supervisor in `sessions` owns the process; this module only decides *what*
to run — the flutter binary, the device selector, the dart-defines for local or
remote API URLs, and release builds.
"""
from __future__ import annotations

import os
import shutil


def which_flutter() -> str | None:
    return shutil.which("flutter")


def run_argv(entry: dict, serial: str, mode: str) -> list[str]:
    """The `flutter run` command line for one project on one device.

    Local mode injects the local API (and websocket) URLs; remote mode injects
    the remote ones. The supervisor appends `--pid-file` so it can signal reload
    and restart without scraping the terminal.
    """
    argv = ["flutter", "run", "-d", serial]
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


def build_argv(entry: dict) -> list[str]:
    remote_api = str(entry.get("api_remote") or "").strip()
    argv = ["flutter", "build", "apk", "--release", f"--dart-define=API_BASE_URL={remote_api}"]
    if entry.get("socket_remote"):
        argv.append(f"--dart-define=SOCKET_BASE_URL={entry['socket_remote']}")
    return argv


def preflight(entry: dict) -> list[str]:
    """Problems that would stop a run before we even try."""
    issues = []
    if not which_flutter():
        issues.append("the flutter command was not found on PATH")
    path = os.path.expanduser(str(entry.get("path") or ""))
    if not os.path.isdir(path):
        issues.append(f"project directory not found: {path}")
    return issues
