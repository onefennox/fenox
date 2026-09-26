"""Every fact about the machine, answered once.

Fenox asks the same questions from several places — the doctor report, the
diagnosis engine, the installer, the Settings page — and the questions are
versioned, path-sensitive and slow (each one may run a subprocess). Two
consequences make this module necessary rather than tidy:

* **One answer per fact.** Two copies of a parser will drift, and when they do
  the product contradicts itself. It already did: `doctor` reported an adb
  version of "1.0.41" (a protocol string frozen since 2014) while the
  connection layer reported the real release, "36.0.0". A tool people depend on
  cannot answer the same question two ways.
* **One cost per fact.** Probes are cached for the life of the process and
  invalidated on demand, so a dashboard refresh does not re-run `flutter
  --version` several times a second.

Nothing here judges or advises. It observes; `connect` decides.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import adb as adb_module
from . import host

# name -> (purpose, required by Fenox, how to install it, how to check the version)
TOOLS: dict[str, tuple[str, bool, str | None, list[str]]] = {
    "adb": ("Talk to Android devices over USB and wireless", True, "android-tools-adb", ["version"]),
    "scrcpy": ("Screen mirroring and control", True, "scrcpy", ["--version"]),
    "flutter": ("Build and run Flutter apps", True, None, ["--version"]),
    "ffmpeg": ("Recording and media conversion", False, "ffmpeg", ["-version"]),
    "tmux": ("Multi-device run sessions and backends", False, "tmux", ["-V"]),
    "git": ("Clone and update projects", False, "git", ["--version"]),
    "node": ("JavaScript backends and the web toolchain", False, "nodejs", ["--version"]),
    "qrencode": ("Show a pairing QR code in the terminal", False, "qrencode", ["--version"]),
    "zbarimg": ("Decode a pairing QR code from an image", False, "zbarimg", ["--version"]),
}

#: Where to read a release number out of a `--version` style output. adb prints
#: two numbers and only one of them is the release.
_RELEASE_PATTERNS = {
    "adb": re.compile(r"^Version\s+(\d+\.\d+(?:\.\d+)?)", re.MULTILINE),
    "flutter": re.compile(r"Flutter\s+(\d+\.\d+\.\d+)"),
    "scrcpy": re.compile(r"scrcpy\s+(\d[\w.]*)"),
}
_FALLBACK_RELEASE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


@dataclass
class Tool:
    """One probed tool."""

    name: str
    path: str
    version: str
    present: bool
    purpose: str = ""
    required: bool = False
    installable: bool = False
    requires_sudo: bool = False
    #: True when `version` is a release number rather than a first line of prose.
    version_is_release: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "version": self.version,
            "present": self.present,
            "purpose": self.purpose,
            "required": self.required,
            "installable": self.installable,
            "requires_sudo": self.requires_sudo,
            "version_is_release": self.version_is_release,
            **self.extra,
        }


def _resolve(name: str, settings: dict) -> str | None:
    """Find a tool the way the rest of Fenox does, not just `shutil.which`.

    adb and Flutter may be configured by the owner, or live outside PATH inside
    an SDK, so a PATH-only lookup reports false negatives on perfectly good
    machines.
    """
    if name == "adb":
        return host.adb_client(settings.get("adb_path"))
    if name == "flutter":
        return host.find_flutter(settings.get("flutter_path"))
    return shutil.which(name)


def _release(name: str, output: str) -> tuple[str, bool]:
    """(version, is_release) for a `--version` output."""
    text = (output or "").strip()
    if not text:
        return ("", False)
    pattern = _RELEASE_PATTERNS.get(name)
    if pattern:
        found = pattern.search(text)
        if found:
            return (found.group(1), True)
    # Unknown tool: the first line is the conventional answer, but it is prose
    # rather than a number, so say so rather than pretending otherwise.
    first = text.splitlines()[0]
    fallback = _FALLBACK_RELEASE.search(first)
    if fallback:
        return (fallback.group(1), True)
    return (first[:80], False)


_cache: dict[str, Tool] = {}


def tool(name: str, settings: dict | None = None, refresh: bool = False) -> Tool:
    """Probe one tool, cached. The only place a tool version is determined."""
    settings = settings or {}
    key = f"{name}|{settings.get('adb_path') or ''}|{settings.get('flutter_path') or ''}"
    if not refresh and key in _cache:
        return _cache[key]

    purpose, required, package, args = TOOLS.get(name, ("", False, None, []))
    binary = _resolve(name, settings)
    version, is_release = ("", False)
    if binary:
        result = host.run([binary, *args], timeout=20)
        version, is_release = _release(name, result.stdout or result.stderr)

    probed = Tool(
        name=name,
        path=binary or "",
        version=version,
        present=binary is not None,
        purpose=purpose,
        required=required,
        installable=package is not None,
        requires_sudo=package is not None,
        version_is_release=is_release,
    )
    _cache[key] = probed
    return probed


def tools(settings: dict | None = None, refresh: bool = False) -> list[Tool]:
    return [tool(name, settings, refresh=refresh) for name in TOOLS]


def invalidate() -> None:
    """Drop cached probes, so the next question is asked of the machine again."""
    _cache.clear()
    _install_cache.clear()
    adb_module.invalidate_version_cache()


# --- adb topology -----------------------------------------------------------

@dataclass
class AdbTopology:
    """Which adb binaries exist, and which server actually holds the devices."""

    client: str
    server: str
    windows_exe: str
    configured_port: int
    active_port: int | None
    version: str
    candidates: list[str]

    def as_dict(self) -> dict:
        return {
            "client": self.client,
            "server": self.server,
            "windows_exe": self.windows_exe,
            "configured_port": self.configured_port,
            "active_port": self.active_port,
            "version": self.version,
            "candidates": list(self.candidates),
        }


def adb_topology(settings: dict | None = None) -> AdbTopology:
    settings = settings or {}
    override = settings.get("adb_path") or None
    return AdbTopology(
        client=host.adb_client(override) or "",
        server=host.adb_server_binary(override) or "",
        windows_exe=host.find_windows_adb() or "",
        configured_port=adb_module.server_port(),
        active_port=adb_module.current_port(),
        version=adb_module.client_version(),
        candidates=list(host.adb_candidates(override)),
    )


#: Probed install lists, kept apart from `_cache` because they hold dicts rather
#: than `Tool`s and are keyed differently.
_install_cache: dict[str, list[dict]] = {}


def adb_installations(settings: dict | None = None) -> list[dict]:
    """Every adb on this machine, with its release.

    More than one is normal — a distro package, a manual SDK and a Homebrew or
    Windows install all coexist on plenty of machines. What matters is whether
    they *agree*: two adbs of different versions will fight over the same device
    and the symptom is a phone that connects and then vanishes, which points
    nowhere near the cause.
    """
    settings = settings or {}
    key = f"installs|{settings.get('adb_path') or ''}"
    if key not in _install_cache:
        rows: list[dict] = []
        for path in host.adb_installations():
            result = host.run([path, "version"], timeout=15)
            version, is_release = _release("adb", result.stdout or result.stderr)
            rows.append({"path": path, "version": version, "is_release": is_release})
        _install_cache[key] = rows
    return list(_install_cache[key])


def conflicting_adbs(settings: dict | None = None) -> list[dict]:
    """Installations whose release differs from the one Fenox will use."""
    settings = settings or {}
    rows = adb_installations(settings)
    if len(rows) < 2:
        return []
    active = adb_topology(settings).version
    if not active:
        return []
    return [row for row in rows if row["version"] and row["version"] != active]


# --- machine facts that decide which fixes apply ---------------------------

def shell() -> str:
    """The shell a fix should be written for: 'posix' or 'powershell'."""
    return "powershell" if host.IS_WINDOWS else "posix"


def fix_runs_in() -> str:
    """Where a fix command has to be run, which is not always this shell.

    On WSL the shell is bash but USB is owned by Windows, so a usbipd command
    has to run in a Windows PowerShell. Telling someone to paste a PowerShell
    command into their WSL prompt is the kind of small wrongness that costs an
    afternoon.
    """
    return "windows" if host.IS_WSL else shell()


def wsl_host_ip() -> str:
    """The Windows host's address as seen from WSL, for reaching adb directly."""
    for candidate in ("/etc/resolv.conf",):
        try:
            for line in Path(candidate).read_text().splitlines():
                if line.startswith("nameserver"):
                    address = line.split()[1]
                    if not address.startswith("127."):
                        return address
        except OSError:
            continue
    return ""


def summary(settings: dict | None = None, refresh: bool = False) -> dict:
    """A compact snapshot for the report and the System page."""
    return {
        "platform": host.HOST.os,
        "python_ok": True,
        "adb": adb_topology(settings).as_dict(),
        "tools": [probed.as_dict() for probed in tools(settings, refresh=refresh)],
    }
