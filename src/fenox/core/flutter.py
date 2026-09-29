"""Flutter command construction and tool discovery.

The flutter binary is resolved through `host`, which checks a configured path
first, then PATH, then the usual install locations. The supervisor owns the
process; this module only decides *what* to run.
"""
from __future__ import annotations

import os
import subprocess

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


_BUILD_ARGV = {
    "apk-debug": ["build", "apk", "--debug"],
    "apk-release": ["build", "apk", "--release"],
    "apk-profile": ["build", "apk", "--profile"],
    "aab-release": ["build", "appbundle", "--release"],
}


def build_argv(flutter: str, entry: dict, kind: str = "apk-release", mode: str | None = None) -> list[str]:
    """The `flutter build` command line for one artifact kind.

    `mode` chooses which backend the app is compiled against, and it is not a
    detail: a release build carrying a localhost URL produces an app that runs
    perfectly and talks to nothing.
    """
    argv = [flutter, *_BUILD_ARGV.get(kind, _BUILD_ARGV["apk-release"])]
    if mode == "local":
        api = str(entry.get("api_local") or "").strip()
        socket = str(entry.get("socket_local") or "").strip()
    else:
        api = str(entry.get("api_remote") or entry.get("api_local") or "").strip()
        socket = str(entry.get("socket_remote") or entry.get("socket_local") or "").strip()
    if api:
        argv.append(f"--dart-define=API_BASE_URL={api}")
    if socket:
        argv.append(f"--dart-define=SOCKET_BASE_URL={socket}")
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


#: Checks a developer runs on a project, and what each one is for. They are
#: grouped here rather than scattered so the UI can offer them without knowing
#: the command lines.
QUALITY_ACTIONS: dict[str, dict] = {
    "analyze": {
        "label": "Analyze",
        "argv": ["analyze"],
        "hint": "Static analysis: errors, lints, dead code.",
        "timeout": 240,
    },
    "test": {
        "label": "Test",
        "argv": ["test"],
        "hint": "Runs the project's test suite.",
        "timeout": 600,
    },
    "outdated": {
        "label": "Outdated packages",
        "argv": ["pub", "outdated"],
        "hint": "Dependencies that have newer versions available.",
        "timeout": 180,
    },
    "doctor": {
        "label": "Doctor",
        "argv": ["doctor", "-v"],
        "hint": "Whether this machine can build the project at all.",
        "timeout": 180,
    },
}


def run_action(flutter: str, entry: dict, action: str) -> tuple[bool, str]:
    """Run one quality action in the project directory.

    Returns (ok, combined output). Output is what the developer needs, so it is
    passed through untouched rather than summarised.
    """
    spec = QUALITY_ACTIONS.get(action)
    if spec is None:
        raise KeyError(f"unknown action: {action}")

    path = os.path.expanduser(str(entry.get("path") or ""))
    if not os.path.isdir(path):
        return False, f"project directory not found: {path}"

    argv = [flutter, *spec["argv"]]
    try:
        result = subprocess.run(
            argv,
            cwd=path,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=float(spec["timeout"]),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return False, f"`flutter {action}` did not finish within {spec['timeout']}s"
    except OSError as exc:
        return False, f"could not run flutter: {exc}"

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return result.returncode == 0, output or "(no output)"
