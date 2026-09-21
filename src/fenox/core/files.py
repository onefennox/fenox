"""Browsing and transferring files on a device.

Listing parses `ls -la`, which every Android build provides. Transfers use
`adb push`/`pull`, and downloads stream the file through `exec-out cat` so a
missing or unreadable file is reported instead of producing a truncated one.
"""
from __future__ import annotations

import posixpath
import shlex
import subprocess


def _shell(serial: str, command: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "shell", command],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def _parse_ls(path: str, output: str) -> list[dict]:
    entries = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line or line.startswith("total"):
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        mode, _links, owner, group, size, date, time, name = parts
        if name in (".", ".."):
            continue
        kind = "dir" if mode.startswith("d") else "link" if mode.startswith("l") else "file"
        target = name
        if kind == "link" and " -> " in name:
            target = name.split(" -> ", 1)[0]
        entries.append({
            "name": target,
            "path": posixpath.join(path, target),
            "type": kind,
            "size": int(size) if size.isdigit() else 0,
            "modified": f"{date} {time}",
            "mode": mode,
            "owner": owner,
            "group": group,
        })
    entries.sort(key=lambda entry: (entry["type"] != "dir", str(entry["name"]).lower()))
    return entries


def list_dir(serial: str, path: str) -> tuple[list[dict] | None, str]:
    path = path or "/sdcard"
    ok, output = _shell(serial, f"ls -la {shlex.quote(path)}")
    if not ok:
        return None, output or f"cannot read {path}"
    return _parse_ls(path, output), ""


def download(serial: str, path: str) -> bytes:
    proc = subprocess.run(
        ["adb", "-s", serial, "exec-out", "cat", path],
        capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or "could not read the file")
    return proc.stdout


def push(serial: str, local_path: str, remote_path: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["adb", "-s", serial, "push", local_path, remote_path],
        capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def pull(serial: str, remote_path: str, local_path: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["adb", "-s", serial, "pull", remote_path, local_path],
        capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def make_dir(serial: str, path: str) -> tuple[bool, str]:
    return _shell(serial, f"mkdir -p {shlex.quote(path)}")


def remove(serial: str, path: str) -> tuple[bool, str]:
    if not path or path in ("/", "/sdcard", "/storage"):
        return False, "refusing to remove that path"
    return _shell(serial, f"rm -rf {shlex.quote(path)}", timeout=60)
