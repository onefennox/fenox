"""Windows `usbipd-win`, the USB/IP bridge that gives WSL access to USB devices.

WSL has no USB passthrough of its own. Microsoft does not implement one either:
support is entirely third-party, so a phone plugged into Windows is invisible to
WSL until `usbipd` bridges it. This module is the whole of Fenox's knowledge of
that bridge, kept in `core` so both the server and the CLI can use it.

Two facts from the usbipd-win project shape everything here:

* `usbipd bind` **persists** across reboots but needs **administrator** rights.
* `usbipd attach --wsl` needs **no** rights but is **not persistent** — it must be
  redone after every reboot, device reset, or unplug/replug.

So Fenox can do the recurring part itself and only ever has to ask the owner for
the one-time `bind`. `attach` is deliberately not run with `--auto-attach`: that
is an endless foreground loop that dies with its console window, whereas the
watcher in `connect` re-attaches on a timer and can log every attempt.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import host

# Where usbipd-win installs. `usbipd` is also added to the Windows PATH, but a
# WSL process does not inherit it, so the well-known locations are checked too.
_CANDIDATES = (
    "/mnt/c/Program Files/usbipd-win/usbipd.exe",
    "/mnt/c/Program Files (x86)/usbipd-win/usbipd.exe",
)

# `1-2`, `2-14`: a bus number, a hyphen, a device number.
_BUSID = re.compile(r"^\d+-\d+$")

# usbipd states, as they appear in the STATE column.
STATE_ATTACHED = "Attached"
STATE_SHARED = "Shared"
STATE_NOT_SHARED = "Not shared"


@dataclass
class UsbipdDevice:
    """One device as `usbipd list` reports it."""

    busid: str
    vid_pid: str
    name: str
    state: str
    persisted: list[str] = field(default_factory=list)

    @property
    def attached(self) -> bool:
        return self.state.startswith(STATE_ATTACHED)

    @property
    def shared(self) -> bool:
        """Bound for sharing. Such a device can be attached without rights."""
        return self.state.startswith(STATE_SHARED) or self.attached

    @property
    def android(self) -> bool:
        """Is this plausibly an Android phone in debugging mode?

        Used only to decide what is worth offering to attach; a wrong guess costs
        the owner one click, whereas filtering too tightly would hide the device.
        """
        known = ("04e8", "18d1", "0bb4", "22b8", "2e95", "05c6", "2717", "12d1", "19d2", "0fce")
        return self.vid_pid.split(":")[0].lower() in known

    @property
    def display_name(self) -> str:
        """A short, readable name.

        usbipd lists every interface a composite device exposes, so the name can
        run to several comma-separated clauses ("SAMSUNG Mobile USB Remote NDIS
        Network Device, SAMSUNG An..."). The first clause is the product.
        """
        head = self.name.split(",")[0].strip()
        return head or self.vid_pid or self.busid


def binary() -> str | None:
    """The usbipd executable, or None when it is not installed."""
    if not host.IS_WSL:
        # Only WSL needs the bridge. Native Linux and macOS see USB directly.
        return shutil.which("usbipd")
    for candidate in _CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("usbipd.exe") or shutil.which("usbipd")


def installed() -> bool:
    return binary() is not None


def version() -> str:
    exe = binary()
    if not exe:
        return ""
    return _run(["--version"], timeout=15)[1].strip().splitlines()[0][:60] if _run(["--version"], 15)[1] else ""


def _run(args: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run usbipd and return (returncode, combined output). Never raises."""
    exe = binary()
    if not exe:
        return (127, "usbipd is not installed")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return (124, f"usbipd {args[0] if args else ''} timed out")
    except OSError as exc:
        return (126, f"could not run usbipd: {exc}")
    return (proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).replace("\r\n", "\n").strip())


def _split_state(line: str) -> tuple[str, str]:
    """Split a device row into (state, name), longest state first.

    `Not shared` must be tried before `Shared`, or every unshared device parses
    as shared with a name ending in "Not".
    """
    for state in (STATE_NOT_SHARED, STATE_ATTACHED, STATE_SHARED):
        if line.rstrip().endswith(state):
            return (state, line.rstrip()[: -len(state)])
    return ("", line)


def parse_list(output: str) -> tuple[list[UsbipdDevice], dict[str, list[str]]]:
    """Parse `usbipd list` into devices and the persisted-attachment map.

    The output is a human-formatted table whose device names contain commas, so
    columns are taken positionally instead of by splitting on a fixed width: the
    bus id and VID:PID are the first two fields, the state is the last, and
    everything between them is the name.
    """
    devices: list[UsbipdDevice] = []
    persisted: dict[str, list[str]] = {}
    section = ""

    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.rstrip(":") in ("Connected", "Persisted"):
            section = line.rstrip(":")
            continue
        if line.startswith("BUSID") or line.startswith("GUID"):
            continue  # header

        fields = line.split()
        if section == "Connected":
            if len(fields) < 4 or not _BUSID.match(fields[0]):
                continue
            # "Not shared" is two words, so the state cannot be taken as the last
            # token: match the state off the end of the line and treat the rest
            # as the name, which itself contains commas and spaces.
            state, name = _split_state(line)
            if not state:
                continue
            # Drop the leading "<busid> <vid:pid>" that _split_state left in place.
            name = re.sub(r"^\S+\s+\S+\s+", "", name).strip()
            devices.append(
                UsbipdDevice(
                    busid=fields[0],
                    vid_pid=fields[1],
                    name=name,
                    state=state,
                )
            )
        elif section == "Persisted":
            if len(fields) < 2:
                continue
            guid = fields[0]
            # Every later line until the next GUID belongs to this device.
            persisted.setdefault(guid, [" ".join(fields[1:])])

    _attach_persisted_names(devices, persisted)
    return (devices, persisted)


def _attach_persisted_names(devices: list[UsbipdDevice], persisted: dict[str, list[str]]) -> None:
    """Note, per device, the persisted entries whose name matches its own.

    A stale persisted auto-attach is a common cause of `Device busy (exported)`,
    so the diagnosis wants to say "this device has an old auto-attach entry".
    Matching on the leading part of the name tolerates usbipd's own truncation.
    """
    for device in devices:
        key = device.name.split(",")[0].strip().lower()
        if not key:
            continue
        for names in persisted.values():
            for name in names:
                if name.split(",")[0].strip().lower() == key:
                    device.persisted.append(name)


def list_devices() -> list[UsbipdDevice]:
    """Devices Windows can see, with their sharing state."""
    if not installed():
        return []
    return parse_list(_run(["list"], timeout=25)[1])[0]


def android_devices() -> list[UsbipdDevice]:
    """Only the devices that look like Android phones in debugging mode."""
    return [device for device in list_devices() if device.android]


def find_device(busid: str) -> UsbipdDevice | None:
    return next((device for device in list_devices() if device.busid == busid), None)


def attach(busid: str) -> tuple[bool, str]:
    """Attach a shared device to WSL. No administrator rights needed.

    Returns (ok, detail). A failure is returned rather than raised: the usual
    causes are all things the owner can be told about, and the watcher retries.
    """
    code, output = _run(["attach", "--wsl", "--busid", busid], timeout=45)
    ok = code == 0
    return (ok, output or f"usbipd attach exited {code}")


def detach(busid: str) -> tuple[bool, str]:
    code, output = _run(["detach", "--busid", busid], timeout=30)
    return (code == 0, output or f"usbipd detach exited {code}")


def bind(busid: str) -> tuple[bool, str]:
    """Share a device. **Needs administrator rights**, so this is guidance only.

    Never called by the hub: `doctor` returns the command for the owner to run.
    """
    code, output = _run(["bind", "--busid", busid], timeout=30)
    return (code == 0, output or f"usbipd bind exited {code}")


def bind_command(busid: str) -> str:
    return f"usbipd bind --busid {busid}"


def install_command() -> str:
    return "winget install --interactive --exact dorssel.usbipd-win"


def unbind_command(busid: str) -> str:
    return f"usbipd unbind --busid {busid}"


def attach_command(busid: str) -> str:
    return f"usbipd attach --wsl --busid {busid}"


def wsl_path_to_windows(path: str) -> str | None:
    """`/mnt/c/Users/x` -> `C:\\Users\\x`, for handing a path to Windows tools."""
    if not host.IS_WSL:
        return None
    resolved = Path(path)
    parts = resolved.parts
    if len(parts) < 3 or parts[1] != "mnt" or len(parts[2]) != 1:
        return None
    return "\\".join([parts[2].upper(), *parts[3:]])
