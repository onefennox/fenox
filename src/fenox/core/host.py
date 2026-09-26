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
    # Windows, where the SDK lands under LOCALAPPDATA and adb carries an
    # extension. Probed on every platform because a Windows SDK can be mounted
    # or shared, and an unreadable candidate is simply skipped.
    "~\\AppData\\Local\\Android\\Sdk",
    "~\\Android\\Sdk",
    "/usr/lib/android-sdk",
    "/opt/android-sdk",
    "/opt/android/sdk",
    # Homebrew, on both Intel and Apple Silicon. Missing these meant a Mac with
    # only `brew install android-platform-tools` looked like it had no adb.
    "/opt/homebrew/share/android-commandlinetools",
    "/usr/local/share/android-commandlinetools",
]

#: Binaries that carry a platform extension. Probed in both forms so a
#: cross-platform candidate list still resolves on the machine running it.
_ADB_NAMES = ("adb", "adb.exe")
_FLUTTER_NAMES = ("flutter", "flutter.bat")


def _first_existing(paths: list[str]) -> str | None:
    for path in paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def android_sdk_roots() -> list[str]:
    roots: list[str] = []
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(os.path.expanduser(value))
    # LOCALAPPDATA is a parent, not the SDK root itself.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(os.path.expanduser(local), "Android", "Sdk"))
    roots += [os.path.expanduser(root) for root in _ANDROID_SDK_ROOTS]
    seen: list[str] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


def adb_candidates(configured: str | None = None) -> list[str]:
    """Every plausible adb binary, in preference order, deduplicated.

    On WSL the Windows adb.exe is the only one that can see USB, so it is
    included alongside the Linux adb used as a client. Both the bare name and
    the platform's executable suffix are probed: a list built on Linux has to
    stay useful when the same code runs on Windows or macOS.
    """
    seen: list[str] = []

    def add(path: str) -> None:
        expanded = os.path.abspath(os.path.expanduser(path))
        if expanded not in seen:
            seen.append(expanded)

    def add_names(directory: str) -> None:
        for name in _ADB_NAMES:
            add(os.path.join(directory, name))

    if configured:
        expanded = os.path.expanduser(configured)
        if os.path.isdir(expanded):
            add_names(expanded)
            add_names(os.path.join(expanded, "platform-tools"))
        else:
            add(expanded)
    value = os.environ.get("FENOX_ADB_PATH")
    if value:
        add(value)
    found = shutil.which("adb") or shutil.which("adb.exe")
    if found:
        add(found)
    for root in android_sdk_roots():
        add_names(os.path.join(root, "platform-tools"))
    for path in ("~/platform-tools", "/opt/platform-tools", "/usr/local/platform-tools",
                 "/snap/bin", "/home/linuxbrew/.linuxbrew/bin", "/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.basename(path) in _ADB_NAMES:
            add(path)
        else:
            add_names(path)
    if WINDOWS_ADB:
        add(WINDOWS_ADB)
    # The Windows SDK location, mapped into WSL, when the distro name is known.
    if HOST.is_wsl and WIN_USER:
        add(f"/mnt/c/Users/{WIN_USER}/AppData/Local/Android/Sdk/platform-tools/adb.exe")
    return seen


def adb_installations() -> list[str]:
    """Every adb on this machine that actually exists, for conflict detection.

    Two adbs of different versions will fight over the same device, and the
    symptom — a phone that connects then vanishes — points nowhere near the
    cause. Surfacing the set is the only way to explain it.
    """
    found: list[str] = []
    for candidate in adb_candidates():
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and candidate not in found:
            found.append(candidate)
    return found


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
    "~/flutter",
    "~/development/flutter",
    "~/.flutter-sdk/flutter",
    "~/.local/share/flutter",
    "~/fvm/default",
    "~/.fvm/default",
    "/opt/flutter",
    "/usr/local/flutter",
    "/usr/lib/flutter",
    "/snap/flutter",
    # Homebrew, Intel and Apple Silicon.
    "/opt/homebrew/share/flutter",
    "/usr/local/share/flutter",
    "/home/linuxbrew/.linuxbrew/share/flutter",
    "~\\flutter",
    "~\\development\\flutter",
    "C:\\src\\flutter",
]


def _flutter_binary_in(root: str) -> list[str]:
    """The flutter launcher inside an SDK root, in every name it can have.

    Windows ships `flutter.bat`, not `flutter`, so a path list that only ever
    mentions the POSIX name silently finds nothing there.
    """
    return [os.path.join(root, "bin", name) for name in _FLUTTER_NAMES]


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
        for name in _FLUTTER_NAMES:
            add(os.path.join(root, ".fvm", "flutter_sdk", "bin", name))
            add(os.path.join(root, ".fvm", "flutter", "bin", name))
        rc = os.path.join(root, ".fvmrc")
        try:
            if os.path.isfile(rc):
                import json as _json
                version = _json.loads(Path(rc).read_text()).get("flutter")
                if version:
                    for name in _FLUTTER_NAMES:
                        add(os.path.join(Path.home(), "fvm", "versions", version, "bin", name))
        except Exception:
            pass
    if configured:
        expanded = os.path.expanduser(configured)
        # Accept either the binary or its directory.
        if os.path.isdir(expanded):
            for name in _FLUTTER_NAMES:
                add(os.path.join(expanded, "bin", name))
                add(os.path.join(expanded, "flutter", "bin", name))
        else:
            add(expanded)
    root_env = os.environ.get("FLUTTER_ROOT")
    if root_env:
        for name in _FLUTTER_NAMES:
            add(os.path.join(root_env, "bin", name))
    for launcher in _FLUTTER_NAMES:
        found = shutil.which(launcher)
        if found:
            add(found)
    # asdf shims sit on PATH under their plain name.
    add(os.path.expanduser("~/.asdf/shims/flutter"))
    # Each candidate is an SDK root, so expand it to its launcher(s).
    for root in FLUTTER_CANDIDATES:
        for path in _flutter_binary_in(os.path.expanduser(root)):
            add(path)
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


# --- browsing the host filesystem ------------------------------------------

#: Never shown in the folder picker: noisy, huge, or irrelevant to picking a
#: project. Kept small and explicit rather than a broad blocklist.
BROWSE_SKIP = {
    ".git", ".cache", ".local", ".npm", ".pub-cache", ".gradle", ".dart_tool",
    ".idea", ".vscode", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".Trash", "snap",
}

#: Guard against a pathological directory (a home with 50k entries) locking the UI.
BROWSE_LIMIT = 1000


def is_flutter_project(path: Path) -> bool:
    """True when `path` is a Flutter app root: a pubspec plus an android/ dir.

    Never raises: the picker walks directories the owner cannot read (a
    root-owned `/lost+found`, for one), and one unreadable entry must not break
    the whole listing.
    """
    try:
        return (path / "pubspec.yaml").is_file() and (path / "android").is_dir()
    except OSError:
        return False


def quick_dirs() -> list[dict[str, str]]:
    """Shortcut entries for the folder picker: home, Projects, and the roots."""
    entries: list[dict[str, str]] = []
    home = Path.home()
    candidates = [("Home", home), ("Projects", home / "Projects"), ("Data", fenox_data_dir())]
    candidates.append(("/", Path("/")))
    for label, path in candidates:
        text = str(path)
        if path.is_dir() and not any(entry["path"] == text for entry in entries):
            entries.append({"label": label, "path": text})
    return entries


def fenox_data_dir() -> Path:
    """The data directory, for the picker's shortcut. Mirrors `config.data_dir`."""
    override = os.environ.get("FENOX_DATA_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg).expanduser() if xdg else home_relative()) / "fenox"


def home_relative() -> Path:
    return Path.home() / ".local" / "share"


def browse_dirs(path: str | None = None) -> dict:
    """List the subdirectories of `path` for the folder picker.

    Returns the resolved directory, its parent (None at the filesystem root), the
    child directories, and where a Flutter app root is. Only directories are
    returned: every caller of this endpoint is choosing a folder, never a file.
    """
    raw = (path or "").strip()
    target = Path(raw).expanduser() if raw else Path.home()
    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        # A bad path is a normal thing to arrive at from a stale bookmark, so
        # fall back to the nearest directory that does exist rather than 500.
        target = _nearest_existing(target)
    if not target.is_dir():
        raise NotADirectoryError(str(target))

    dirs: list[dict[str, object]] = []
    truncated = False
    try:
        entries = sorted(os.scandir(target), key=lambda e: e.name.lower())
    except OSError as exc:
        raise PermissionError(str(target)) from exc
    for entry in entries:
        if len(dirs) >= BROWSE_LIMIT:
            truncated = True
            break
        try:
            if not entry.is_dir() or entry.name in BROWSE_SKIP or entry.name.startswith("."):
                continue
        except OSError:
            continue  # a dangling symlink or a race; skip it rather than fail
        child = Path(entry.path)
        dirs.append({"name": entry.name, "path": str(child), "flutter": is_flutter_project(child)})
    parent = target.parent if target.parent != target else None
    return {
        "path": str(target),
        "parent": str(parent) if parent else None,
        "dirs": dirs,
        "truncated": truncated,
        "flutter": is_flutter_project(target),
        "quick": quick_dirs(),
    }


def _nearest_existing(path: Path) -> Path:
    """Walk up from `path` until something exists, so the picker can recover."""
    for candidate in [path, *path.parents]:
        if candidate.is_dir():
            return candidate
    return Path.home()


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
