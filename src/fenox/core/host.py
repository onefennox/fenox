"""Host environment: what machine are we on, where is adb, where do captures go.

On WSL the Linux adb server cannot see USB devices, so the Windows `adb.exe` on a
dedicated port is the only way to reach a plugged-in phone. This module answers
those questions once, so the hub, the CLI and the doctor never disagree.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"
IS_WSL = os.path.exists("/proc/version") and (
    "microsoft" in Path("/proc/version").read_text().lower() or bool(os.environ.get("WSL_DISTRO_NAME"))
)


def _win_user() -> str | None:
    """Best-effort Windows username (WSL only)."""
    if not IS_WSL:
        return None
    try:
        for cand in Path("/mnt/c/Users").iterdir():
            if (
                cand.name not in ("Public", "Default", "Default User", "All Users")
                and not cand.name.startswith("desktop.ini")
                and cand.is_dir()
                and (cand / "NTUSER.DAT").exists()
            ):
                return cand.name
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["/mnt/c/Windows/System32/cmd.exe", "/c", "echo %USERNAME%"],
            capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL,
        ).stdout.strip()
        if out and out != "%USERNAME%":
            return out
    except Exception:
        pass
    return None


WIN_USER = _win_user()


def find_windows_adb() -> str | None:
    """Locate Windows adb.exe in the usual places (WSL only)."""
    if not IS_WSL:
        return None
    candidates = ["/mnt/c/platform-tools/adb.exe"]
    if WIN_USER:
        candidates += [
            f"/mnt/c/Users/{WIN_USER}/AppData/Local/Android/Sdk/platform-tools/adb.exe",
            f"/mnt/c/Users/{WIN_USER}/Android/Sdk/platform-tools/adb.exe",
        ]
    candidates += ["/mnt/c/Android/platform-tools/adb.exe", "/mnt/c/tools/platform-tools/adb.exe"]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    try:
        out = subprocess.run(
            ["/mnt/c/Windows/System32/cmd.exe", "/c", "where adb"],
            capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL,
        ).stdout.strip().splitlines()
        if out:
            winpath = out[-1].strip()
            drive, rest = winpath[0].lower(), winpath[2:].replace("\\", "/")
            mapped = f"/mnt/{drive}{rest}"
            if os.path.exists(mapped):
                return mapped
    except Exception:
        pass
    return None


ADB_EXE = find_windows_adb() or "/mnt/c/platform-tools/adb.exe"


def run_cmd(cmd: str, timeout: float | None = None) -> str:
    """Run a shell command, return stripped stdout, "" on any failure.

    Children get /dev/null on stdin: a Windows interop call reading the terminal
    used to steal the user's next keystroke.
    """
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL,
        ).stdout.strip()
    except Exception:
        return ""


def capture_root() -> Path:
    """Where screenshots and recordings go: Windows Desktop on WSL, else ~/Fenox."""
    if IS_WSL and WIN_USER and Path("/mnt/c/Users").is_dir():
        return Path(f"/mnt/c/Users/{WIN_USER}/Desktop/Fenox")
    return Path.home() / "Fenox"


def output_dirs() -> dict[str, Path]:
    root = capture_root()
    return {
        "screenshot": root / "Screenshots",
        "record": root / "Recordings",
        "logs": root / "Logs",
        "apk": root / "APKs",
    }


def ensure_output_dirs() -> None:
    for path in output_dirs().values():
        path.mkdir(parents=True, exist_ok=True)
