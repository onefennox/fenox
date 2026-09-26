"""The adb layer: one shared server, device listing, connect, pairing discovery.

adb is resolved through `host`, so on Linux we use the local adb and on WSL we
prefer the Windows adb that can see USB. Commands are passed as argument lists
with a Python-side timeout, never through a shell.
"""
from __future__ import annotations

import os
import re
import socket
import time

from . import host

DEFAULT_SERVER_PORT = 5038

# Remember the shell's original value so the doctor can explain a mismatch.
SHELL_ADB_PORT = os.environ.get("ANDROID_ADB_SERVER_PORT")


def server_port() -> int:
    try:
        return int(os.environ.get("FENOX_ADB_PORT", DEFAULT_SERVER_PORT))
    except ValueError:
        return DEFAULT_SERVER_PORT


def configure_environment(port: int | None = None) -> int:
    """Point this process and every child at the adb server holding the devices."""
    resolved = port or detect_port()
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(resolved)
    return resolved


def _client() -> str | None:
    return host.adb_client()


# The port is not assumed: it is the port whose server actually holds the
# devices. Forcing a fixed port let a USB-blind Linux adb server squat it while
# the user's phone sat on the Windows server's default port.
_active_port: int | None = None


def _is_device_line(line: str) -> bool:
    parts = line.strip().split()
    if len(parts) < 2 or line.strip().startswith("List"):
        return False
    return parts[1] in ("device", "unauthorized", "offline", "bootloader", "recovery")


def _port_has_devices(binary: str, port: int) -> tuple[bool, bool]:
    """(responded, has_devices) for a port, probed with the server binary."""
    result = host.run([binary, "-P", str(port), "devices"], timeout=6)
    text = result.stdout
    if "List of devices" not in text:
        return False, False
    return True, any(_is_device_line(line) for line in text.splitlines())


def detect_port(force: bool = False) -> int:
    """The adb port to use: the first that has devices, else one that responds.

    Checks the configured port first, then adb's default 5037, which on WSL is
    where the Windows server (the only one that sees USB) normally lives.
    """
    global _active_port
    if _active_port is not None and not force:
        return _active_port
    configured = server_port()
    binary = host.adb_server_binary()
    if binary is None:
        _active_port = configured
        return configured

    ports: list[int] = []
    for candidate in (configured, 5037, 5038):
        if candidate not in ports:
            ports.append(candidate)
    responding: int | None = None
    for port in ports:
        responded, has_devices = _port_has_devices(binary, port)
        if responded and has_devices:
            _active_port = port
            return port
        if responded and responding is None:
            responding = port
    _active_port = responding or configured
    return _active_port


def current_port() -> int | None:
    """The detected port, or None if detection has not run yet."""
    return _active_port


def _run(args: list[str], timeout: float = 10) -> host.Result:
    client = _client()
    if client is None:
        return host.Result(False, None, "", "adb was not found on this machine")
    return host.run([client, "-P", str(detect_port()), *args], timeout=timeout)


_version_cache: str | None = None


def invalidate_version_cache() -> None:
    """Forget the cached release, so the next call re-asks the machine."""
    global _version_cache
    _version_cache = None


def client_version() -> str:
    """The adb *release* as a string, e.g. "36.0.0".

    Not the protocol version: `adb version` prints two numbers, and the first
    ("Android Debug Bridge version 1.0.41") has been frozen for years. The
    release is the "Version 36.0.0-13206524" line, which is the number that
    decides which wireless features exist. Cached: it cannot change while the
    hub runs. Returns "" when adb cannot be run.
    """
    global _version_cache
    if _version_cache is not None:
        return _version_cache
    result = _run(["version"], timeout=10)
    # Prefer the "Version x.y.z" line; fall back to the last dotted number.
    match = re.search(r"^Version\s+(\d+\.\d+\.\d+)", result.stdout or "", re.MULTILINE)
    if not match:
        found = re.findall(r"\d+\.\d+\.\d+", result.stdout or "")
        match = None
        _version_cache = found[-1] if found else ""
    else:
        _version_cache = match.group(1)
    return _version_cache


def ensure_server(force: bool = False) -> bool:
    """Make sure an adb server that can see devices is running.

    The port is chosen by `detect_port`, so an existing server (the Windows one
    on WSL, which is the only one that sees USB) is reused rather than displaced.
    """
    global _active_port, _devices_cache
    server = host.adb_server_binary()
    if server is None:
        return False
    if force:
        _active_port = None
    port = detect_port(force=force)
    responded, _ = _port_has_devices(server, port)
    if responded:
        return True
    host.run([server, "-P", str(port), "start-server"], timeout=10)
    _devices_cache = {"ts": 0.0, "out": ""}
    return True


_devices_cache: dict = {"ts": 0.0, "out": ""}


def devices_output() -> str:
    """`adb devices` output, cached briefly so one screen refresh is one call."""
    now = time.time()
    if now - _devices_cache["ts"] < 1.5:
        return _devices_cache["out"]
    result = _run(["devices"], timeout=5)
    out = result.stdout if result.ok else ""
    _devices_cache.update(ts=time.time(), out=out)
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
    result = _run(["connect", f"{ip}:{port}"], timeout=8)
    text = result.stdout or result.stderr
    ok = any(token in text.lower() for token in ("connected", "already connected"))
    return ok, text


def mdns_port(ip: str) -> str | None:
    for service in mdns_services():
        if service["kind"] == "connect" and service["ip"] == ip:
            return service["port"]
    return None


# The three mDNS services a phone can advertise. `_adb-tls-pairing` is the one
# that matters most and is the one usually missed: a phone publishes it only
# while the "Pair device with pairing code" dialog is open, which is precisely
# when the owner is looking at the code and needs to be told where to type it.
_MDNS_KINDS = (
    ("_adb-tls-pairing", "pairing"),
    ("_adb-tls-connect", "connect"),
    ("_adb._tcp", "legacy"),
)


def _parse_mdns_address(token: str) -> tuple[str, str] | None:
    """`192.168.1.20:37895` -> ('192.168.1.20', '37895'), or None."""
    if ":" not in token:
        return None
    host, _, port = token.rpartition(":")
    if not port.isdigit() or not host:
        return None
    return (host.strip("[]"), port)


def mdns_services() -> list[dict[str, str]]:
    """Phones advertising wireless debugging, as adb's mDNS broker sees them.

    Returns [{"kind": pairing|connect|legacy, "ip": ..., "port": ...,
    "name": ...}].

    The listing is "<instance> <service type> <address>", but the columns are
    located by content rather than position: usbipd-era adb builds and the IPv6
    form add or reorder columns, and an address is the only field that looks
    like `host:port`. A phone may advertise both IPv4 and IPv6; IPv4 is kept,
    because it is the form that works across NAT and WSL alike.
    """
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in _run(["mdns", "services"], timeout=8).stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        # Most specific first: "_adb-tls-connect" is a substring of nothing else,
        # but "_adb._tcp" would otherwise match the legacy service inside the
        # fully-qualified name of a TLS service.
        kind = next((name for token, name in _MDNS_KINDS if token in line), "")
        if not kind:
            continue
        instance = next((part for part in parts if part.startswith("adb-") or part.startswith("studio-")), parts[0])
        for token in parts:
            address = _parse_mdns_address(token)
            if not address:
                continue
            ip, port = address
            key = (kind, ip, port)
            if key in seen:
                continue
            seen.add(key)
            found.append({"kind": kind, "ip": ip, "port": port, "name": instance})
            break  # one address per service is enough
    return found


def mdns_candidates() -> list[tuple[str, str]]:
    """[(ip, port)] phones advertising wireless debugging."""
    return [(service["ip"], service["port"]) for service in mdns_services() if service["kind"] == "connect"]


def mdns_pairing_candidates() -> list[dict[str, str]]:
    """Phones currently showing a pairing code and waiting to be paired."""
    return [service for service in mdns_services() if service["kind"] == "pairing"]


def pair(ip: str, port: str | int, code: str) -> tuple[bool, str]:
    result = _run(["pair", f"{ip}:{port}", code], timeout=20)
    text = result.stdout or result.stderr
    return "Successfully paired" in text, text


def reverse(serial: str, ports: list[str | int]) -> None:
    for port in ports:
        _run(["-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}"], timeout=8)


def shell(serial: str, command: str, timeout: int = 40) -> str:
    return _run(["-s", serial, "shell", command], timeout=timeout).stdout


def getprop(serial: str, prop: str, timeout: int = 4) -> str:
    return _run(["-s", serial, "shell", "getprop", prop], timeout=timeout).stdout.strip()


def local_ip() -> str:
    """This machine's outbound local IP, without shelling out."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()
