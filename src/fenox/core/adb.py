"""The adb layer: one shared server, device listing, connect, pairing discovery.

On WSL the Linux adb server cannot see USB devices, so every part of Fenox routes
adb traffic to the Windows adb server on a dedicated port. This module is the one
place that knows that, so the hub, the CLI and the doctor cannot disagree about
which server holds the devices.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

from .host import ADB_EXE, run_cmd

DEFAULT_SERVER_PORT = 5038

# Adb honours ANDROID_ADB_SERVER_PORT; set it for this process and every child
# (flutter, scrcpy, adb) so they all see the same devices. Remember the shell's
# original value so the doctor can explain a mismatch.
SHELL_ADB_PORT = os.environ.get("ANDROID_ADB_SERVER_PORT")


def server_port() -> int:
    try:
        return int(os.environ.get("FENOX_ADB_PORT", DEFAULT_SERVER_PORT))
    except ValueError:
        return DEFAULT_SERVER_PORT


def configure_environment(port: int | None = None) -> int:
    """Point this process and its children at the shared adb server."""
    resolved = port or server_port()
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(resolved)
    return resolved


def ensure_server() -> None:
    """Make sure the shared adb server is listening (idempotent, silent)."""
    port = configure_environment()
    try:
        probe = subprocess.run(
            [ADB_EXE, "-P", str(port), "devices"],
            capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL,
        )
        if probe.returncode == 0 and "List of devices" in probe.stdout:
            return
    except Exception:
        pass
    try:
        # Under mirrored networking a Linux adb server may have squatted the
        # shared port (it cannot see USB). Evict it so Windows adb can bind.
        squat = run_cmd("ss -tlnp 2>/dev/null")
        for line in squat.splitlines():
            if f":{port} " in line and "adb" in line:
                match = re.search(r"pid=(\d+)", line)
                if match:
                    run_cmd(f"kill {match.group(1)} 2>/dev/null")
                    time.sleep(1)
                break
    except Exception:
        pass
    try:
        subprocess.run(
            ["/mnt/c/Windows/System32/taskkill.exe", "/IM", "adb.exe", "/F"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
        )
        time.sleep(1)
        subprocess.Popen(
            [ADB_EXE, "-P", str(port), "start-server"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
    except Exception:
        pass


_devices_cache: dict = {"ts": 0.0, "out": ""}


def devices_output() -> str:
    """`adb devices` output, cached briefly so one screen refresh is one call."""
    import time as _time

    now = _time.time()
    if now - _devices_cache["ts"] < 1.5:
        return _devices_cache["out"]
    out = run_cmd("timeout 5 adb devices")
    _devices_cache.update(ts=_time.time(), out=out)
    return out


def connected_ids() -> list[str]:
    raw = [
        line.strip().split()[0]
        for line in devices_output().splitlines()
        if line.strip() and "device" in line and not line.strip().startswith("List")
    ]
    ip_based = {d for d in raw if d.count(".") == 3 and ":" in d}
    filtered = []
    for device_id in raw:
        if "_adb-tls-connect" in device_id and any(device_id.split(".")[0] in ip for ip in ip_based):
            continue
        filtered.append(device_id)
    return filtered


def pending_devices() -> list[tuple[str, str]]:
    """Visible but unusable ids: [(id, 'unauthorized'|'offline')]."""
    pending = []
    for line in devices_output().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] in ("unauthorized", "offline"):
            pending.append((parts[0], parts[1]))
    return pending


def connect(ip: str, port: str | int) -> tuple[bool, str]:
    result = run_cmd(f"timeout 8 adb connect {ip}:{port}")
    ok = any(token in result.lower() for token in ("connected", "already connected"))
    return ok, result


def mdns_port(ip: str) -> str | None:
    """The current wireless-debugging port for an IP, via mDNS."""
    for line in run_cmd("adb mdns services 2>/dev/null").splitlines():
        if ip in line and "_adb-tls-connect" in line:
            parts = line.split()
            if len(parts) >= 3 and ":" in parts[2]:
                return parts[2].split(":")[1]
    return None


def mdns_candidates() -> list[tuple[str, str]]:
    """[(ip, port)] phones advertising wireless debugging."""
    found = []
    for line in run_cmd("timeout 6 adb mdns services 2>/dev/null").splitlines():
        if "_adb-tls-connect" not in line:
            continue
        parts = line.split()
        addr = parts[2] if len(parts) >= 3 else ""
        if ":" in addr:
            ip, port = addr.rsplit(":", 1)
            if ip and port.isdigit():
                found.append((ip, port))
    return found


def pair(ip: str, port: str | int, code: str) -> tuple[bool, str]:
    result = run_cmd(f"adb pair {ip}:{port} {code}")
    return "Successfully paired" in result, result


def reverse(serial: str, ports: list[str | int]) -> None:
    for port in ports:
        run_cmd(f"adb -s {serial} reverse tcp:{port} tcp:{port}")


def shell(serial: str, command: str, timeout: int = 40) -> str:
    return run_cmd(f"timeout {timeout} adb -s {serial} shell {command}")


def getprop(serial: str, prop: str, timeout: int = 4) -> str:
    return run_cmd(f"timeout {timeout} adb -s {serial} shell getprop {prop}").strip()


def local_ip() -> str:
    """This machine's local IP, for wireless pairing."""
    ip = run_cmd("ip route get 1 2>/dev/null | awk '{print $(NF-2); exit}'")
    if ip:
        return ip
    ip = run_cmd("hostname -I 2>/dev/null | awk '{print $1}'")
    if ip:
        return ip
    return run_cmd("ifconfig 2>/dev/null | grep 'inet ' | grep -v 127.0.0.1 | awk '{print $2}' | head -1")
