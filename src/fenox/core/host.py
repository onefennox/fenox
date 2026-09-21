"""The host machine: what OS this is, where adb and Flutter live, and how to run
commands without assuming a shell.

Detection is centralised here so the installer, the CLI, the doctor and the hub
all agree. The target for now is Linux and WSL; the shape of this module is what
lets macOS and Windows be added later without touching callers.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def detect_os() -> str:
    """One of linux, wsl, macos, windows (or the raw platform string)."""
    if sys.platform.startswith("linux"):
        try:
            content = Path("/proc/version").read_text().lower()
        except OSError:
            content = ""
        if "microsoft" in content or os.environ.get("WSL_DISTRO_NAME"):
            return "wsl"
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return sys.platform


@dataclass(frozen=True)
class Host:
    os: str

    @property
    def is_linux(self) -> bool:
        return self.os == "linux"

    @property
    def is_wsl(self) -> bool:
        return self.os == "wsl"

    @property
    def is_macos(self) -> bool:
        return self.os == "macos"

    @property
    def is_windows(self) -> bool:
        return self.os == "windows"

    @property
    def supports_local_devices(self) -> bool:
        """Whether a locally attached phone can be seen without a Windows bridge."""
        return self.os in ("linux", "macos")


HOST = Host(os=detect_os())
IS_LINUX = HOST.is_linux
IS_WSL = HOST.is_wsl
IS_MACOS = HOST.is_macos
IS_WINDOWS = HOST.is_windows


# --- Windows side (WSL) ----------------------------------------------------

def _win_user() -> str | None:
    if not HOST.is_wsl:
        return None
    users = Path("/mnt/c/Users")
    try:
        for candidate in users.iterdir():
            if (
                candidate.name not in ("Public", "Default", "Default User", "All Users")
                and not candidate.name.startswith("desktop.ini")
                and candidate.is_dir()
                and (candidate / "NTUSER.DAT").exists()
            ):
                return candidate.name
    except OSError:
        pass
    return None


WIN_USER = _win_user()


def find_windows_adb() -> str | None:
    """Locate Windows adb.exe on WSL, where USB is only visible to Windows."""
    if not HOST.is_wsl:
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


WINDOWS_ADB = find_windows_adb()


# --- adb resolution --------------------------------------------------------

# Android SDK roots, per platform, plus the common standalone platform-tools
# installs. ANDROID_HOME and ANDROID_SDK_ROOT, when set, win.
_ANDROID_SDK_ROOTS = [
    "~/Android/Sdk",
    "~/Android/sdk",
    "~/Library/Android/sdk",
    "~/Library/Android/Sdk",
    "/usr/lib/android-sdk",
    "/opt/android-sdk",
    "/opt/android/sdk",
]


def android_sdk_roots() -> list[str]:
    roots: list[str] = []
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(variable)
        if value:
            roots.append(os.path.expanduser(value))
    roots += [os.path.expanduser(root) for root in _ANDROID_SDK_ROOTS]
    seen: list[str] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


def adb_candidates(configured: str | None = None) -> list[str]:
    """Every plausible adb binary, in preference order, deduplicated.

    On WSL the Windows adb.exe is the only one that can see USB, so it is
    included alongside the Linux adb used as a client.
    """
    seen: list[str] = []

    def add(path: str) -> None:
        expanded = os.path.abspath(os.path.expanduser(path))
        if expanded not in seen:
            seen.append(expanded)

    if configured:
        expanded = os.path.expanduser(configured)
        add(os.path.join(expanded, "adb") if os.path.isdir(expanded) else expanded)
    for variable in ("FENOX_ADB_PATH",):
        value = os.environ.get(variable)
        if value:
            add(value)
    found = shutil.which("adb")
    if found:
        add(found)
    for root in android_sdk_roots():
        add(os.path.join(root, "platform-tools", "adb"))
    for path in ("~/platform-tools/adb", "/opt/platform-tools/adb", "/usr/local/platform-tools/adb",
                 "/snap/bin/adb", "/home/linuxbrew/.linuxbrew/bin/adb"):
        add(path)
    if WINDOWS_ADB:
        add(WINDOWS_ADB)
    # The Windows SDK location, mapped into WSL, when the distro name is known.
    if HOST.is_wsl and WIN_USER:
        add(f"/mnt/c/Users/{WIN_USER}/AppData/Local/Android/Sdk/platform-tools/adb.exe")
    return seen


def adb_client(configured: str | None = None) -> str | None:
    """The adb used to talk to the server. On WSL, a Linux adb client talks to
    the Windows server; the Windows adb is used directly when no Linux one exists."""
    for candidate in adb_candidates(configured):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def adb_server_binary(configured: str | None = None) -> str | None:
    """The adb that starts and owns the shared server. On WSL that is Windows adb,
    because only it can see USB devices."""
    if HOST.is_wsl and WINDOWS_ADB and os.path.exists(WINDOWS_ADB):
        return WINDOWS_ADB
    return adb_client(configured)


# Kept for callers that only need the server path.
ADB_EXE = adb_server_binary() or "/mnt/c/platform-tools/adb.exe"


# --- Flutter resolution ----------------------------------------------------

FLUTTER_CANDIDATES = [
    "~/flutter/bin/flutter",
    "~/development/flutter/bin/flutter",
    "~/.flutter-sdk/flutter/bin/flutter",
    "~/.local/share/flutter/bin/flutter",
    "~/fvm/default/bin/flutter",
    "~/.fvm/default/bin/flutter",
    "~/.asdf/shims/flutter",
    "/opt/flutter/bin/flutter",
    "/usr/local/flutter/bin/flutter",
    "/usr/lib/flutter/bin/flutter",
    "/snap/bin/flutter",
    "/home/linuxbrew/.linuxbrew/bin/flutter",
]


def flutter_candidates(configured: str | None = None, project: str | None = None) -> list[str]:
    """Every plausible flutter binary, in preference order, deduplicated.

    A per-project SDK (FVM) is preferred for that project, then an explicit
    setting, then FLUTTER_ROOT, then PATH, then the common install locations.
    """
    seen: list[str] = []

    def add(path: str) -> None:
        expanded = os.path.abspath(os.path.expanduser(path))
        if expanded not in seen:
            seen.append(expanded)

    if project:
        root = os.path.expanduser(project)
        # FVM keeps a per-project SDK, and may record it in .fvmrc / .fvm/fvm_config.json.
        add(os.path.join(root, ".fvm", "flutter_sdk", "bin", "flutter"))
        add(os.path.join(root, ".fvm", "flutter", "bin", "flutter"))
        rc = os.path.join(root, ".fvmrc")
        try:
            if os.path.isfile(rc):
                import json as _json
                version = _json.loads(Path(rc).read_text()).get("flutter")
                if version:
                    add(os.path.join(Path.home(), "fvm", "versions", version, "bin", "flutter"))
        except Exception:
            pass
    if configured:
        expanded = os.path.expanduser(configured)
        # Accept either the binary or its directory.
        if os.path.isdir(expanded):
            add(os.path.join(expanded, "bin", "flutter"))
            add(os.path.join(expanded, "flutter", "bin", "flutter"))
        else:
            add(expanded)
    root_env = os.environ.get("FLUTTER_ROOT")
    if root_env:
        add(os.path.join(root_env, "bin", "flutter"))
    found = shutil.which("flutter")
    if found:
        add(found)
    for candidate in FLUTTER_CANDIDATES:
        add(candidate)
    return seen


def find_flutter(configured: str | None = None, project: str | None = None) -> str | None:
    for candidate in flutter_candidates(configured, project):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# --- commands --------------------------------------------------------------

@dataclass
class Result:
    ok: bool
    code: int | None
    stdout: str
    stderr: str


def run(args: list[str], timeout: float | None = None, cwd: str | None = None,
        env: dict | None = None) -> Result:
    """Run a program directly, with a Python-side timeout and no shell.

    Arguments are passed as a list so nothing reaches a shell, and the timeout is
    enforced by the interpreter rather than a `timeout` binary, which keeps this
    usable on platforms that do not ship one.
    """
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return Result(False, None, "", "timed out")
    except FileNotFoundError:
        return Result(False, None, "", f"not found: {args[0]}")
    except Exception as exc:
        return Result(False, None, "", f"{type(exc).__name__}: {exc}")
    return Result(proc.returncode == 0, proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def run_cmd(cmd: str, timeout: float | None = None) -> str:
    """Run a shell command and return stripped stdout, "" on any failure.

    Retained for the few places that genuinely need shell syntax; prefer `run`.
    """
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL,
        ).stdout.strip()
    except Exception:
        return ""


# --- output directories ----------------------------------------------------

def capture_root() -> Path:
    """Where screenshots and recordings go: Windows Desktop on WSL, else ~/Fenox."""
    if HOST.is_wsl and WIN_USER and Path("/mnt/c/Users").is_dir():
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
