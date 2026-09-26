"""The device registry: what we know, what is online, and what just appeared.

Registered devices live in the store; everything here maps that registry onto the
live adb world — telemetry, connection, plug-and-play auto-detection for USB,
emulators and mDNS wireless phones, and the background watcher the hub and the
dashboard run.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import adb, connect
from .host import run_cmd
from .log import get_logger

log = get_logger("devices")

TELEMETRY_TTL = 15
_WIRELESS_SCAN = {"ts": 0.0}
WIRELESS_SCAN_INTERVAL = 15
# Latest wireless scan result, for surfaces that show "needs pairing".
LAST_WIRELESS: dict = {"added": [], "pending": [], "ts": 0.0}

_telemetry_cache: dict = {}
_lock = threading.RLock()


def is_enabled(info: dict) -> bool:
    return not info.get("disabled", False)


def _administer(serial: str, command: str) -> str:
    return run_cmd(f"timeout 5 adb -s {serial} {command}")


def telemetry(serial: str, force: bool = False) -> dict:
    now = time.time()
    cached = _telemetry_cache.get(serial)
    if cached and not force and (now - cached["ts"]) < TELEMETRY_TTL:
        return cached["data"]
    data: dict[str, object] = {
        "battery": "?", "charging": None, "screen": "?", "android": "?", "storage": "?", "app": "?", "model": "?",
    }
    try:
        for line in _administer(serial, "shell dumpsys battery").splitlines():
            line = line.strip()
            if line.startswith("level:"):
                data["battery"] = line.split(":", 1)[1].strip()
            elif line.startswith("status:"):
                data["charging"] = line.split(":", 1)[1].strip() == "2"
        for line in _administer(serial, "shell dumpsys power").splitlines():
            if "mWakefulness=" in line:
                value = line.split("mWakefulness=")[1].split(" ")[0].strip()
                data["screen"] = "On" if value == "Awake" else "Off"
                break
        data["android"] = _administer(serial, "shell getprop ro.build.version.release").strip() or "?"
        for line in _administer(serial, "shell df /data 2>/dev/null").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] != "Filesystem":
                data["storage"] = parts[4]
                break
        import re

        for line in _administer(serial, "shell dumpsys activity activities 2>/dev/null").splitlines():
            if "topResumedActivity" in line or "mFocusedApp" in line:
                match = re.search(r"ActivityRecord\{[^}]*\s+[^/]+/([^}\s]+)", line)
                if match:
                    data["app"] = match.group(1).split(".")[-1]
                    break
        data["model"] = _administer(serial, "shell getprop ro.product.model").strip() or "?"
    except Exception:
        pass
    _telemetry_cache[serial] = {"ts": now, "data": data}
    return data


def telemetry_many(serials: list[str]) -> None:
    if not serials:
        return
    with ThreadPoolExecutor(max_workers=min(8, max(2, len(serials)))) as pool:
        list(pool.map(telemetry, serials))


def _remember_port(store, alias: str, port: str | int) -> None:
    if not port:
        return
    info = store.device(alias) or {}
    history = [p for p in info.get("port_history", []) if str(p) != str(port)]
    history.insert(0, str(port))
    info["port_history"] = history[:5]
    info["port"] = str(port)
    store.upsert_device(alias, info)


def _device_for_serial(store, serial: str) -> str | None:
    for alias, info in store.devices().items():
        if str(info.get("serial", "")) == serial:
            return alias
    return None


def live_serial(store, alias: str, connected: list[str] | None = None) -> str | None:
    """The adb serial for an alias if it is *already* connected (no network I/O).

    Safe to call for every row in a list: it never attempts a connect.
    """
    info = store.device(alias)
    if not info or not is_enabled(info):
        return None
    connected = connected if connected is not None else adb.connected_ids()
    kind = info.get("type")
    if kind == "emulator":
        return next((d for d in connected if d.startswith("emulator-")), None)
    if kind == "usb":
        serial = str(info.get("serial", "") or "")
        for device_id in connected:
            if device_id.startswith("emulator-") or ":" in device_id:
                continue
            if serial and device_id != serial:
                continue
            return device_id
        return None
    ip = info.get("ip")
    if not ip:
        return None
    return next((d for d in connected if ip in d), None)


def resolve_serial(store, alias: str) -> str | None:
    """The live adb serial for a registered alias, or None if offline.

    Emulators match by prefix, USB by serial, wireless by IP with an mDNS port
    refresh and the saved port history as fallback.
    """
    live = live_serial(store, alias)
    if live:
        return live
    info = store.device(alias)
    if not info or not is_enabled(info) or info.get("type") in ("usb", "emulator"):
        return None
    ip = info.get("ip")
    if not ip:
        return None
    advertised = adb.mdns_port(ip)
    candidates = [advertised] if advertised else []
    if info.get("port"):
        candidates.append(str(info["port"]))
    candidates += [str(p) for p in info.get("port_history", [])]
    for port in dict.fromkeys(candidates):
        ok, _ = adb.connect(ip, port)
        if ok:
            _remember_port(store, alias, port)
            return next((d for d in adb.connected_ids() if ip in d), None)
    return None


def autodetect(store) -> list[str]:
    """Register any connected device that is missing from the store.

    Returns the aliases added, so callers can announce them. Honors
    FENOX_NO_AUTODETECT so tests and scripts stay hermetic.
    """
    import os

    if os.environ.get("FENOX_NO_AUTODETECT"):
        return []
    with _lock:
        connected = adb.connected_ids()
        if not connected:
            return []
        devices = store.devices()
        added: list[str] = []
        emulator = next((d for d in connected if d.startswith("emulator-")), None)
        if emulator and not any(info.get("type") == "emulator" for info in devices.values()):
            store.upsert_device("emulator", {"type": "emulator", "model": "Android Emulator", "port": emulator.split("-")[1]})
            added.append("emulator")
        known = {str(info.get("serial", "")) for info in devices.values()}
        for device_id in connected:
            if device_id.startswith("emulator-") or ":" in device_id or device_id in known:
                continue
            model = adb.getprop(device_id, "ro.product.model") or "USB device"
            base = (model or "usbphone").replace(" ", "").replace("_", "").lower() or "usbphone"
            name, n = base, 2
            while name in store.devices():
                name, n = f"{base}{n}", n + 1
            store.upsert_device(name, {"type": "usb", "serial": device_id, "model": model})
            known.add(device_id)
            added.append(name)
        return added


def autodetect_wireless(store, force: bool = False) -> tuple[list[str], list[tuple[str, str]]]:
    """Connect phones advertising wireless debugging, with no user input.

    Returns (added, pending). Throttled unless `force`, and honors
    FENOX_NO_AUTODETECT.
    """
    import os

    if os.environ.get("FENOX_NO_AUTODETECT"):
        return [], []
    now = time.time()
    if not force and now - _WIRELESS_SCAN["ts"] < WIRELESS_SCAN_INTERVAL:
        return [], []
    _WIRELESS_SCAN["ts"] = now
    candidates = adb.mdns_candidates()
    if not candidates:
        LAST_WIRELESS.update(added=[], pending=[], ts=now)
        return [], []
    connected = adb.connected_ids()
    live, pending = [], []
    for ip, port in candidates:
        if any(ip in c for c in connected):
            continue
        ok, _ = adb.connect(ip, port)
        if ok:
            live.append((ip, port, adb.getprop(f"{ip}:{port}", "ro.product.model")))
        else:
            pending.append((ip, port))
    added: list[str] = []
    with _lock:
        devices = store.devices()
        for ip, port, model in live:
            existing = next((k for k, v in devices.items() if v.get("ip") == ip), None)
            if existing:
                _remember_port(store, existing, port)
                continue
            if model and any(
                v.get("type") == "usb" and v.get("model") == model and str(v.get("serial", "")) in connected
                for v in devices.values()
            ):
                continue
            base = (model or "phone").replace(" ", "").replace("_", "").lower() or "phone"
            name, n = base, 2
            while name in store.devices():
                name, n = f"{base}{n}", n + 1
            store.upsert_device(name, {"type": "wireless", "ip": ip, "model": model or "Android device", "port": port})
            added.append(name)
        LAST_WIRELESS.update(added=added, pending=pending, ts=now)
    return added, pending


def reconnect_known_wireless(store) -> None:
    """Re-establish saved wireless devices whose port changes every session."""
    import os

    if os.environ.get("FENOX_NO_AUTODETECT"):
        return
    for alias, info in store.devices().items():
        if info.get("type") in ("usb", "emulator") or not is_enabled(info):
            continue
        if info.get("ip"):
            resolve_serial(store, alias)


class DeviceWatcher:
    """Background plug-and-play while the hub is running.

    Keeps USB, emulator and mDNS wireless devices appearing as they come online,
    and re-establishes saved wireless devices whose port changed.
    """

    def __init__(self, store, interval: int = 5, announce=None):
        self.store = store
        self.interval = interval
        self.announce = announce
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> DeviceWatcher:
        import os

        if os.environ.get("FENOX_NO_AUTODETECT"):
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fenox-watcher")
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                added = autodetect(self.store)
                wireless_added, _ = autodetect_wireless(self.store)
                if self.announce and (added or wireless_added):
                    self.announce(added + wireless_added)
                reconnect_known_wireless(self.store)
                # USB on WSL is bridged by usbipd, and those attachments do not
                # survive a reboot or a replug. Re-establish them here so the
                # owner never has to run a command for it.
                connect.repair_usbipd()
            except Exception as exc:  # a watcher must not die on one bad poll
                log.warning("device poll failed: %s", exc, exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
