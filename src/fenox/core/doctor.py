"""Environment checks and guided tool installation.

Detection is read-only and always safe. Installation is deliberately split: tools
that need root return the exact command for the owner to run themselves, and only
tools that can be installed without root are executed by the hub. Fenox never
runs `sudo` for you.
"""
from __future__ import annotations

import os
import subprocess

from . import adb, connect, env, host, mirror

# name, what it is for, whether Fenox needs it, and how to get it.
TOOLS = [
    ("adb", "Talk to Android devices over USB and wireless", True, "android-tools-adb"),
    ("scrcpy", "Screen mirroring and control", True, "scrcpy"),
    ("flutter", "Build and run Flutter apps", True, None),
    ("tmux", "Multi-device run sessions and backends", False, "tmux"),
    ("ffmpeg", "Recording and media conversion", False, "ffmpeg"),
    ("git", "Clone and update projects", False, "git"),
    ("node", "JavaScript backends and the web toolchain", False, "nodejs"),
    ("qrencode", "Show a pairing QR code in the terminal", False, "qrencode"),
    ("zbarimg", "Decode a pairing QR code from an image", False, "zbarimg"),
]

_VERSION_ARGS = {
    "adb": ["version"],
    "scrcpy": ["--version"],
    "flutter": ["--version"],
    "tmux": ["-V"],
    "ffmpeg": ["-version"],
    "git": ["--version"],
    "node": ["--version"],
}

MANUAL = {
    "flutter": "https://docs.flutter.dev/get-started/install/linux",
}


def _version(binary: str, name: str) -> str:
    args = _VERSION_ARGS.get(name)
    if not args:
        return ""
    try:
        proc = subprocess.run([binary, *args], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except Exception:
        return ""
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return first[0][:80] if first else ""


def _binary_for(name: str, settings: dict) -> str | None:
    """Deprecated: `env.tool` is the single owner of tool resolution and version.

    Kept so existing callers keep working, but it no longer parses anything — the
    two implementations of "what version is this adb" is how the product ended up
    contradicting itself.
    """
    return env.tool(name, settings).path or None


def _check_tool(name: str, settings: dict) -> dict:
    return env.tool(name, settings).as_dict()


def checks(settings: dict | None = None, store=None, deep: bool = True) -> dict:
    """The environment, plus what is actually wrong with it.

    This used to be an inventory that reported presence and was confident about
    USB being usable. On a WSL machine whose phone was plugged in and
    unreachable it printed every tool as `ok` and stated that USB devices were
    visible through the Windows adb, which was the reason it was useless: a
    report that says everything is fine on a machine where nothing works is
    worse than no report.

    So the tool list is still here, but the verdict comes from `connect`, and a
    claim about device visibility is only ever made after devices were actually
    seen.
    """
    settings = settings or {}
    topology = env.adb_topology(settings)
    tool_rows = [probed.as_dict() for probed in env.tools(settings)]
    by_name = {row["name"]: row for row in tool_rows}
    for row in tool_rows:
        row["manual"] = MANUAL.get(row["name"])

    findings = connect.diagnose(store, deep=deep)
    connected = adb.connected_ids()

    notes: list[dict] = []
    if host.IS_WSL:
        if topology.windows_exe:
            notes.append({
                "tone": "ok",
                "text": f"Windows adb found at {topology.windows_exe}; Fenox will use it for USB devices.",
            })
        else:
            notes.append({
                "tone": "warn",
                "text": (
                    "Windows adb was not found. USB debugging over WSL needs Android Platform "
                    "Tools installed on Windows; wireless debugging does not."
                ),
            })
    if connected:
        notes.append({"tone": "ok", "text": f"adb is serving {len(connected)} device(s)."})
    elif not [finding for finding in findings if finding.severity == connect.ERROR]:
        notes.append({
            "tone": "info",
            "text": "No devices are connected right now. That is expected on an idle machine.",
        })

    return {
        "platform": {"linux": host.IS_LINUX, "wsl": host.IS_WSL, "macos": host.IS_MACOS},
        "adb": {
            "windows_exe": topology.windows_exe,
            "server_port": topology.configured_port,
            "active_port": topology.active_port,
            "version": topology.version,
        },
        "tools": tool_rows,
        "notes": notes,
        "findings": [finding.as_dict() for finding in findings],
        "connected": connected,
        "ok": not [finding for finding in findings if finding.severity == connect.ERROR],
        # Kept so a caller can still ask "is this tool usable" without the
        # duplicated resolution logic that used to live here.
        "required_missing": [name for name, row in by_name.items() if row["required"] and not row["present"]],
    }


def tools(settings: dict | None = None) -> dict:
    """How each critical tool was resolved, and what was considered.

    This is what the installer and the Settings page use to explain *why* a tool
    was or was not found, instead of only reporting presence.
    """
    settings = settings or {}
    adb_path = settings.get("adb_path") or None
    flutter_path = settings.get("flutter_path") or None
    return {
        "os": host.HOST.os,
        "adb": {
            "client": host.adb_client(adb_path),
            "server": host.adb_server_binary(adb_path),
            "port": adb.server_port(),
            "detected_port": adb.current_port(),
            "candidates": host.adb_candidates(adb_path),
            "env": {key: os.environ.get(key) for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_ADB_SERVER_PORT")},
        },
        "flutter": {
            "path": host.find_flutter(flutter_path),
            "candidates": host.flutter_candidates(flutter_path),
            "env": {"FLUTTER_ROOT": os.environ.get("FLUTTER_ROOT")},
        },
        "scrcpy": {
            "binary": mirror.scrcpy_binary(),
            "version": mirror.scrcpy_version(),
            "server": mirror.server_path(),
        },
    }


def install_plan(name: str) -> dict:
    """How to install a tool: a root command to run, or a manual link."""
    for tool, _purpose, _required, package in TOOLS:
        if tool != name:
            continue
        if package is None:
            return {"tool": name, "requires_sudo": False, "manual": MANUAL.get(name, ""),
                    "note": "Install this from its official instructions."}
        return {
            "tool": name,
            "requires_sudo": True,
            "command": f"sudo apt-get install -y {package}",
            "note": "Run this yourself; Fenox does not run sudo.",
        }
    raise KeyError(f"unknown tool: {name}")


def run_install(name: str) -> dict:
    """Execute an install only when it does not need root, else return the command."""
    plan = install_plan(name)
    if plan.get("manual"):
        return {"ok": False, "requires_sudo": False, "manual": plan["manual"], "note": plan.get("note", "")}
    if plan.get("requires_sudo"):
        return {"ok": False, "requires_sudo": True, "command": plan["command"], "note": plan["note"]}
    command = plan.get("command")
    if not command:
        return {"ok": False, "note": "no automatic installer for this tool"}
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return {"ok": False, "note": str(exc)}
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()[-4000:]}
