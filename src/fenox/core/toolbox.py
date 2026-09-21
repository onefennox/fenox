"""Device actions: screen, input, apps, files, control, and diagnostics.

Everything talks to one device over adb. Shell commands are passed as argument
lists, never through a local shell, so the device shell sees exactly what we
intend and message content can never reach the host shell.
"""
from __future__ import annotations

import re
import subprocess

MAX_RECORD_SECONDS = 60
_KEYEVENT = re.compile(r"^(?:KEYCODE_)?([A-Z0-9_]+)$")


def _run(serial: str, args: list[str], timeout: int = 30) -> tuple[bool, bytes]:
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, *args],
            capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return False, b"timed out"
    except Exception as exc:
        return False, str(exc).encode()
    ok = proc.returncode == 0
    return ok, proc.stdout if ok else (proc.stdout + proc.stderr)


def _shell(serial: str, command: str, timeout: int = 30) -> tuple[bool, str]:
    ok, output = _run(serial, ["shell", command], timeout=timeout)
    return ok, output.decode("utf-8", "replace").strip()


# -- screen ----------------------------------------------------------------

def screenshot(serial: str) -> bytes:
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=30, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("screenshot timed out") from exc
    if proc.returncode != 0 or not proc.stdout.startswith(b"\x89PNG"):
        raise RuntimeError("could not read a screenshot from the device")
    return proc.stdout


def record(serial: str, seconds: int = 10) -> bytes:
    seconds = max(1, min(int(seconds), MAX_RECORD_SECONDS))
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screenrecord", "--output-format=h264", f"--time-limit={seconds}", "-"],
            capture_output=True, timeout=seconds + 30, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("recording timed out") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("could not record the screen on the device")
    return proc.stdout


def wake(serial: str) -> tuple[bool, str]:
    return _shell(serial, "input keyevent KEYCODE_WAKEUP")


def lock(serial: str) -> tuple[bool, str]:
    return _shell(serial, "input keyevent KEYCODE_SLEEP")


# -- input -----------------------------------------------------------------

def input_text(serial: str, text: str) -> tuple[bool, str]:
    safe = str(text).replace(" ", "%s")
    return _shell(serial, f'input text "{safe}"')


def tap(serial: str, x: int, y: int) -> tuple[bool, str]:
    return _shell(serial, f"input tap {int(x)} {int(y)}")


def swipe(serial: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> tuple[bool, str]:
    return _shell(serial, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration)}")


def keyevent(serial: str, code: str) -> tuple[bool, str]:
    match = _KEYEVENT.match(str(code).strip().upper())
    name = f"KEYCODE_{match.group(1)}" if match else str(code)
    return _shell(serial, f"input keyevent {name}")


def open_url(serial: str, url: str) -> tuple[bool, str]:
    target = url if str(url).startswith(("http://", "https://")) else f"https://{url}"
    return _shell(serial, f'am start -a android.intent.action.VIEW -d "{target}"')


def clipboard_set(serial: str, text: str) -> tuple[bool, str]:
    return _shell(serial, f'am broadcast -a clipper.set -e text "{text}"')


def clipboard_read(serial: str) -> str:
    _, output = _shell(serial, "service call clipboard 2 i32 1")
    return output


# -- apps ------------------------------------------------------------------

def list_packages(serial: str, third_party: bool = True) -> list[str]:
    flag = " -3" if third_party else ""
    ok, output = _shell(serial, f"pm list packages{flag}", timeout=40)
    if not ok:
        return []
    return sorted(line.replace("package:", "").strip() for line in output.splitlines() if line.startswith("package:"))


def install_apk(serial: str, local_path: str) -> tuple[bool, str]:
    ok, output = _run(serial, ["install", "-r", local_path], timeout=300)
    text = output.decode("utf-8", "replace").strip()
    return ("Success" in text), text


def uninstall(serial: str, package: str) -> tuple[bool, str]:
    return _run_str(serial, ["uninstall", package], timeout=120)


def clear_data(serial: str, package: str) -> tuple[bool, str]:
    return _run_str(serial, ["shell", "pm", "clear", package])


def force_stop(serial: str, package: str) -> tuple[bool, str]:
    return _run_str(serial, ["shell", "am", "force-stop", package])


def app_info(serial: str, package: str) -> tuple[bool, str]:
    return _shell(serial, f"dumpsys package {package}", timeout=40)


def launch(serial: str, package: str) -> tuple[bool, str]:
    return _shell(serial, f"monkey -p {package} -c android.intent.category.LAUNCHER 1")


def _run_str(serial: str, args: list[str], timeout: int = 30) -> tuple[bool, str]:
    ok, output = _run(serial, args, timeout=timeout)
    return ok, output.decode("utf-8", "replace").strip()


# -- device control --------------------------------------------------------

def reboot(serial: str, mode: str = "") -> tuple[bool, str]:
    mode = (mode or "").strip()
    if mode not in ("", "recovery", "bootloader", "sideload"):
        return False, "unsupported reboot mode"
    ok, output = _shell(serial, f"reboot {mode}".strip())
    return ok, output or "reboot sent"


def set_volume(serial: str, level: int) -> tuple[bool, str]:
    level = max(0, min(int(level), 100))
    return _shell(serial, f"media volume --stream 3 --set {level}")


def set_brightness(serial: str, level: int) -> tuple[bool, str]:
    level = max(0, min(int(level), 255))
    return _shell(serial, f"settings put system screen_brightness {level}")


def _svc(serial: str, service: str, enable: bool) -> tuple[bool, str]:
    return _shell(serial, f"svc {service} {'enable' if enable else 'disable'}")


def toggle_wifi(serial: str, enable: bool) -> tuple[bool, str]:
    return _svc(serial, "wifi", enable)


def toggle_data(serial: str, enable: bool) -> tuple[bool, str]:
    return _svc(serial, "data", enable)


def toggle_bluetooth(serial: str, enable: bool) -> tuple[bool, str]:
    return _svc(serial, "bluetooth", enable)


def send_notification(serial: str, title: str, text: str) -> tuple[bool, str]:
    return _shell(serial, f'cmd notification post -S bigtext -t "{title}" fenox "{text}"')


def read_notifications(serial: str) -> str:
    _, output = _shell(serial, "dumpsys notification --noredact", timeout=40)
    return output


# -- diagnostics -----------------------------------------------------------

_PROP_LABELS = {
    "ro.product.manufacturer": "manufacturer",
    "ro.product.model": "model",
    "ro.build.version.release": "android",
    "ro.build.version.sdk": "sdk",
    "ro.product.cpu.abi": "abi",
    "gsm.version.baseband": "baseband",
}


def device_props(serial: str) -> dict:
    props: dict[str, str] = {}
    for prop, label in _PROP_LABELS.items():
        _, value = _shell(serial, f"getprop {prop}")
        props[label] = value or "—"
    return props


def battery(serial: str) -> dict:
    _, output = _shell(serial, "dumpsys battery")
    data: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


def storage(serial: str) -> str:
    _, output = _shell(serial, "df -h /data /storage/emulated/0 2>/dev/null")
    return output


def processes(serial: str) -> list[str]:
    _, output = _shell(serial, "ps -A -o PID,USER,NAME 2>/dev/null", timeout=40)
    return output.splitlines()


def ip_address(serial: str) -> str:
    _, output = _shell(serial, "ip route | grep wlan")
    return output
