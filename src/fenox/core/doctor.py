"""Environment checks and guided tool installation.

Detection is read-only and always safe. Installation is deliberately split: tools
that need root return the exact command for the owner to run themselves, and only
tools that can be installed without root are executed by the hub. Fenox never
runs `sudo` for you.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from . import adb, host, mirror

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
    """Resolve a tool the same way the rest of Fenox does.

    adb and Flutter are special: they may be configured, or live somewhere
    outside PATH, so `shutil.which` alone would report false negatives.
    """
    if name == "adb":
        return host.adb_client(settings.get("adb_path"))
    if name == "flutter":
        return host.find_flutter(settings.get("flutter_path"))
    return shutil.which(name)


def _check_tool(name: str, settings: dict) -> dict:
    binary = _binary_for(name, settings)
    return {
        "name": name,
        "present": binary is not None,
        "version": _version(binary, name) if binary else "",
        "path": binary or "",
    }


def checks(settings: dict | None = None) -> dict:
    """Environment report: each tool, the adb topology, and platform notes."""
    settings = settings or {}
    tools = []
    for name, purpose, required, package in TOOLS:
        found = _check_tool(name, settings)
        found.update({
            "purpose": purpose,
            "required": required,
            "installable": package is not None,
            "requires_sudo": package is not None,
            "manual": MANUAL.get(name),
        })
        tools.append(found)

    windows_adb = host.find_windows_adb()
    notes = []
    if host.IS_WSL:
        if windows_adb:
            notes.append({"tone": "ok", "text": f"Windows adb found at {windows_adb}; USB devices are visible through it."})
        else:
            notes.append({
                "tone": "warn",
                "text": "Windows adb was not found. USB debugging over WSL needs Android Platform Tools installed on Windows.",
            })

    return {
        "platform": {"linux": host.IS_LINUX, "wsl": host.IS_WSL, "macos": host.IS_MACOS},
        "adb": {"windows_exe": windows_adb, "server_port": adb.server_port()},
        "tools": tools,
        "notes": notes,
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
