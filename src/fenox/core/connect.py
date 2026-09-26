"""Why a phone is not connected, and what to do about it.

The failure this exists to prevent: a phone is plugged in, authorised and
healthy, and Fenox reports nothing at all. That is what a WSL machine looks like
when `usbipd` has not bridged the device, and it is indistinguishable from "no
phone" unless something looks.

So the model here is deliberately different from a boolean "is it connected".
`diagnose` returns *findings* — each one saying what is wrong, why, and the exact
command that fixes it — and marks whether Fenox may fix it itself. Anything
Fenox can do without administrator rights it does; anything that needs rights is
returned as a command for the owner, never run behind their back.

Findings are ordered most-actionable first and de-duplicated per device, so the
UI shows the one thing to do rather than every symptom of it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import adb, env, host, usbipd
from .log import get_logger

log = get_logger("connect")

ERROR = "error"
WARN = "warn"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}


@dataclass
class Finding:
    """One problem, with the remedy attached.

    `id` is the *problem*, not the instance: `usbipd.not_attached` is a stable
    key the UI and any future automation can rely on, and `scope` says which
    device it is about. Keying on the instance instead (`usbipd-attach-1-2`)
    would make every consumer re-parse a string to learn what went wrong.
    """

    id: str
    severity: str
    title: str
    detail: str
    #: The exact command that fixes it, when a command is what is needed.
    fix: str | None = None
    #: True when Fenox can carry out `fix` itself, without administrator rights.
    auto: bool = False
    #: What the finding is about: a usbipd bus id, or a device alias.
    scope: str | None = None
    #: Extra steps to run after `fix`, in order.
    also: list[str] = field(default_factory=list)
    #: Where the commands have to be run: "here", or "windows" when the shell
    #: the owner is looking at is not the one that owns the device.
    runs_in: str = "here"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "fix": self.fix,
            "auto": self.auto,
            "scope": self.scope,
            "also": list(self.also),
            "runs_in": self.runs_in,
        }


# --- individual checks ------------------------------------------------------

def _check_usbipd_installed() -> list[Finding]:
    """WSL cannot see USB at all until usbipd-win is installed on Windows."""
    if not host.IS_WSL or usbipd.installed():
        return []
    return [
        Finding(
            id="usbipd.missing",
            severity=ERROR,
            title="USB devices cannot reach WSL on this machine",
            detail=(
                "WSL has no USB passthrough of its own, so a phone plugged into Windows is "
                "invisible to Fenox until the usbipd-win bridge is installed. This is a "
                "one-time setup for the whole machine. Wireless debugging needs none of it."
            ),
            fix=usbipd.install_command(),
            also=[f"then: {usbipd.attach_command('<busid>')}"],
            runs_in="windows",
        )
    ]


def _check_windows_android_devices() -> list[Finding]:
    """Bridge what Windows can see into WSL, or say exactly what is missing."""
    if not host.IS_WSL or not usbipd.installed():
        return []

    findings: list[Finding] = []
    for device in usbipd.android_devices():
        name = device.display_name

        if device.attached:
            # Bridged. If adb still cannot see it, that is a different problem
            # and the generic adb checks will say so.
            continue

        if device.state.startswith(usbipd.STATE_SHARED):
            # Bound already, so attaching needs no rights: Fenox can do it.
            findings.append(
                Finding(
                    id="usbipd.not_attached",
                    severity=WARN,
                    title=f"{name} is shared with Windows but not attached to WSL",
                    detail=(
                        "The phone is plugged in and shared, but WSL cannot use it yet. "
                        "Fenox can attach it; the attachment does not survive a reboot or "
                        "an unplug, so Fenox will keep re-attaching it for you."
                    ),
                    fix=usbipd.attach_command(device.busid),
                    auto=True,
                    scope=device.busid,
                    runs_in="windows",
                )
            )
        else:
            findings.append(
                Finding(
                    id="usbipd.unbound",
                    severity=ERROR,
                    title=f"{name} is not shared with WSL",
                    detail=(
                        "The phone is plugged into Windows, but WSL cannot see it until the "
                        "device is shared. Sharing is a one-time action per device and "
                        "survives reboots."
                    ),
                    fix=usbipd.bind_command(device.busid),
                    scope=device.busid,
                    runs_in="windows",
                )
            )
    return findings


def _check_stale_export(store) -> list[Finding]:
    """A device that is shared, still not attached, and refused to attach.

    `Device busy (exported)` means usbipd holds an export for the device that no
    longer resolves — typically a persisted auto-attach from an earlier session.
    Attaching cannot succeed until that is cleared, and clearing it needs
    administrator rights, so this is reported rather than retried forever.

    Read from what previous attempts actually returned rather than by trying
    again here: `diagnose` is a read-only question, and the background loop is
    already attaching on a timer. Probing from here would mean every poll of the
    dashboard mutated the machine.
    """
    if not host.IS_WSL or not usbipd.installed():
        return []

    findings: list[Finding] = []
    for device in usbipd.android_devices():
        if device.attached or not device.state.startswith(usbipd.STATE_SHARED):
            continue
        failure = _export_failures.get(device.busid, "")
        if "exported" not in failure.lower():
            continue

        name = device.display_name
        stale = bool(device.persisted)
        findings.append(
            Finding(
                id="usbipd.stale_export",
                severity=ERROR,
                title=f"{name} is held by a stale usbipd export",
                detail=(
                    "Attaching fails with “Device busy (exported)”. usbipd is holding an "
                    "export for this device that no longer resolves"
                    + (
                        f" — there {'' if len(device.persisted) == 1 else 'are'} "
                        f"{len(device.persisted)} saved auto-attach entr"
                        f"{'y' if len(device.persisted) == 1 else 'ies'} for it."
                        if stale
                        else ", usually left over from an earlier session."
                    )
                    + " Clearing it needs an Administrator PowerShell, once."
                ),
                fix=usbipd.unbind_command(device.busid),
                also=[
                    usbipd.bind_command(device.busid),
                    usbipd.attach_command(device.busid),
                ],
                scope=device.busid,
                runs_in="windows",
            )
        )
    return findings


def _check_adb_present() -> list[Finding]:
    if adb._client() or adb._active_port is not None:
        return []
    if host.IS_WSL and not host.find_windows_adb():
        return [
            Finding(
                id="adb.missing",
                severity=ERROR,
                title="Android Platform Tools were not found on Windows",
                detail=(
                    "On WSL, USB devices are only reachable through the Windows adb. "
                    "Install Android Platform Tools on Windows, or use wireless debugging."
                ),
                fix="winget install Google.PlatformTools",
            )
        ]
    return [
        Finding(
            id="adb.missing",
            severity=ERROR,
            title="adb was not found",
            detail="Fenox needs adb to talk to any Android device.",
            fix="sudo apt install android-tools-adb",
        )
    ]


def _check_stale_adb_entry(store) -> list[Finding]:
    """adb lists a device that the USB bridge does not actually have attached.

    This is the state a phone is left in when the bridge drops underneath it: a
    drop is not always clean, so adb can keep listing a serial that no longer
    answers. It is worth naming precisely because the obvious reflex — restarting
    the adb server — tears down *every* device, including ones that were fine,
    and on WSL it takes the USB attachment with it. That reflex is what turns one
    flaky cable into an afternoon.
    """
    if not host.IS_WSL or not usbipd.installed():
        return []

    attached = {device.busid for device in usbipd.list_devices() if device.attached}
    if attached:
        return []  # the bridge is working; trust adb

    # A USB/IP attachment that vanishes mid-session is the usual cause, and the
    # bridge is the thing to check rather than adb.
    listed = [
        line.split()[0]
        for line in _device_lines()
        if len(line.split()) >= 2 and line.split()[1] in ("device", "offline", "unauthorized")
    ]
    if not listed:
        return []

    return [
        Finding(
            id="device.stale_adb_entry",
            severity=WARN,
            title=f"adb still lists {len(listed)} device(s) that are not actually attached",
            detail=(
                "The USB bridge has no device attached, but adb has not noticed yet. This is "
                "what a dropped connection looks like from the two sides. Do not restart the "
                "adb server to clear it: that disconnects every device you have and, on WSL, "
                "takes the USB attachment down with it. Fenox will re-attach on its own; if it "
                "does not, unplug and replug the cable."
            ),
            fix=None,
            auto=True,
        )
    ]


def _check_pending(store) -> list[Finding]:
    """Devices adb knows about but has not finished authorising."""
    findings: list[Finding] = []
    for line in _device_lines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "unauthorized":
            findings.append(
                Finding(
                    id="device.unauthorized",
                    severity=INFO,
                    title=f"{parts[0]} is waiting for approval",
                    detail=(
                        "The phone is connected but has not granted this computer permission. "
                        "Unlock it and accept the “Allow USB debugging?” prompt, tick "
                        "“Always allow”, then it will connect on its own."
                    ),
                    scope=parts[0],
                )
            )
    return findings


def _device_lines() -> list[str]:
    result = adb._run(["devices"], timeout=10)
    return [line for line in result.stdout.splitlines() if line.strip() and not line.startswith("List")]


def _check_adb_version() -> list[Finding]:
    """Platform Tools 37 / Android 17 made wireless debugging self-healing.

    Worth saying out loud, because it changes how much the owner has to think
    about wireless connections: on 37+ a paired phone reconnects by itself
    whenever it rejoins a network it has been paired on.
    """
    version = adb.client_version()
    if not version or _adb_tuple(version) >= (37, 0):
        return []
    return [
        Finding(
            id="adb.too_old",
            severity=INFO,
            title="Updating Platform Tools makes wireless connections self-healing",
            detail=(
                f"adb {version} is installed. Platform Tools 37 (Android 17) introduced ADB "
                "Wi-Fi 2.0, where a paired phone reconnects on its own whenever it rejoins a "
                "network it was paired on, and connections survive sleep and network changes. "
                "Everything still works without it — it just asks more of you."
            ),
            fix="sdkmanager --install \"platform-tools\"",
            also=["or download the latest Platform Tools from developer.android.com/tools/releases/platform-tools"],
        )
    ]


def _adb_tuple(version: str) -> tuple[int, ...]:
    found = re.findall(r"\d+", str(version or ""))
    return tuple(int(part) for part in found) if found else (0,)


# --- the diagnosis ----------------------------------------------------------

def _check_udev_permissions() -> list[Finding]:
    """A device is on the bus, but this user cannot open it.

    The Linux equivalent of "the phone is plugged in and fenox sees nothing".
    udev normally hands `/dev/bus/usb` to the `plugdev` group; a user who has
    never been added to it gets a device that `lsusb` shows and adb cannot open.
    Nothing anywhere says "permissions", so the symptom is identical to a missing
    phone.

    Only native Linux: on WSL the device is reached through Windows, where this
    does not apply.
    """
    if host.IS_WSL or not host.IS_LINUX:
        return []
    bus = Path("/dev/bus/usb")
    if not bus.is_dir():
        return []

    # Nothing plugged in is not a permissions problem.
    try:
        has_devices = any(entry.name.isdigit() for entry in bus.iterdir() if entry.is_dir())
    except OSError:
        return [
            Finding(
                id="usb.bus_unreadable",
                severity=ERROR,
                title="Cannot read /dev/bus/usb",
                detail=(
                    "The USB bus exists but this user cannot list it, so no device can be "
                    "opened. This is a permissions problem, not a missing phone."
                ),
                fix="sudo apt install usbutils",
            )
        ]
    if not has_devices:
        return []

    # Devices exist. Can this user actually open one?
    if _first_device(bus) is None or _can_open_first_device(bus):
        return []

    in_plugdev = "plugdev" in _group_names()
    detail = (
        "A USB device is plugged in, but this user cannot open it. udev normally gives "
        "/dev/bus/usb to the `plugdev` group, and this account is not in it"
        if not in_plugdev
        else "A USB device is plugged in, but this user still cannot open it, even though "
        "the account is in the plugdev group. The device may need a replug for a new rule to apply."
    )
    return [
        Finding(
            id="usb.permissions",
            severity=ERROR,
            title="This user cannot open the USB device",
            detail=(
                f"{detail} Until that is fixed, every phone looks like it is not plugged in — "
                "which is indistinguishable from a missing cable."
            ),
            fix="sudo usermod -aG plugdev $USER",
            also=["then log out and back in (or reboot) and replug the device"],
            runs_in="here",
        )
    ]


def _first_device(bus: Path):
    """The first real device node under /dev/bus/usb, or None."""
    try:
        for bus_dir in sorted(bus.iterdir()):
            if not bus_dir.is_dir() or not bus_dir.name.isdigit():
                continue
            for device in sorted(bus_dir.iterdir()):
                if device.name.isdigit():
                    return device
    except OSError:
        return None
    return None


def _can_open_first_device(bus: Path) -> bool:
    device = _first_device(bus)
    return device is not None and os.access(device, os.R_OK | os.W_OK)


def _group_names() -> set[str]:
    """Supplementary group names for this process."""
    import grp

    names: set[str] = set()
    try:
        groups = os.getgroups() or [os.getgid()]
    except OSError:
        groups = []
    for gid in groups:
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except (KeyError, OSError):
            continue
    return names


def _check_android_toolchain() -> list[Finding]:
    """Whether Flutter can actually build for a device.

    A Flutter install that cannot build is a common and deeply confusing state:
    `flutter run` fails on a licence message that looks nothing like a licence
    problem. Only checked in the deep pass because it runs the SDK's own doctor,
    which takes seconds.
    """
    probed = env.tool("flutter", {})
    if not probed.present:
        return []  # reported already as a missing tool

    result = host.run([probed.path, "doctor", "-v"], timeout=90)
    text = f"{result.stdout}\n{result.stderr}"
    if not text.strip():
        return []

    findings: list[Finding] = []
    if re.search(r"android licen[cs]e.*(unknown|not accepted|unaccepted)", text, re.IGNORECASE) or (
        "Android license status unknown" in text
    ):
        findings.append(
            Finding(
                id="android.licenses_unaccepted",
                severity=ERROR,
                title="Android SDK licences have not been accepted",
                detail=(
                    "Flutter cannot build or install anything for Android until the SDK "
                    "licences are accepted. Builds fail with a message that does not mention "
                    "licences, which makes this hard to recognise. Java must be installed "
                    "first if it is not already."
                ),
                fix="flutter doctor --android-licenses",
            )
        )
    if re.search(r"Android Studio .*not installed", text) and "cmdline-tools" in text.lower():
        findings.append(
            Finding(
                id="android.cmdline_tools_missing",
                severity=WARN,
                title="Android SDK command-line tools are missing",
                detail=(
                    "Android Studio is not installed, so the SDK tools that live with it are "
                    "missing too. Licences cannot be accepted and some builds will fail."
                ),
                fix="sdkmanager --install \"cmdline-tools;latest\"",
            )
        )
    return findings


def _check_adb_conflicts(settings: dict | None = None) -> list[Finding]:
    """Several adb installs, and they do not agree on their version.

    A machine accumulates adb binaries: a distro package, a manual SDK, a
    Homebrew or Windows install. While they are the same version this is
    harmless. The moment they diverge, two servers compete for the same device
    and the phone appears, then disappears, then reappears — a failure whose
    cause is nowhere in the symptom.
    """
    try:
        clashes = env.conflicting_adbs(settings or {})
    except Exception:  # probing is best-effort and must never break diagnosis
        return []
    if not clashes:
        return []

    active = env.adb_topology(settings or {}).version
    others = ", ".join(f"{row['version']} at {row['path']}" for row in clashes[:4])
    extra = "" if len(clashes) <= 4 else f" (and {len(clashes) - 4} more)"
    return [
        Finding(
            id="adb.conflicting_installations",
            severity=WARN,
            title="Several adb installations, and their versions differ",
            detail=(
                f"Fenox is using adb {active}, but other adb binaries on this machine report a "
                f"different version: {others}{extra}. Competing adb servers take a device away "
                "from each other, which looks like a flaky cable or a phone dropping out. "
                "Point Fenox at one adb, or remove the others."
            ),
            fix="fenox config set adb_path /path/to/the/adb/you/want",
        )
    ]


def diagnose(store=None, deep: bool = False) -> list[Finding]:
    """Everything that is currently stopping a device from being usable.

    `deep` adds the checks that are slow enough not to run on a poll — the
    Flutter/Android toolchain in particular, which shells out to `flutter doctor`
    and takes seconds. The dashboard uses the fast pass; `fenox doctor` asks for
    both, so a report is complete while a refresh stays cheap.

    Ordered most-actionable first, and collapsed to one finding per device so
    the owner sees the next thing to do rather than all of its symptoms.
    """
    findings: list[Finding] = []
    findings += _check_usbipd_installed()
    findings += _check_stale_export(store)
    findings += _check_windows_android_devices()
    findings += _check_adb_present()
    findings += _check_stale_adb_entry(store)
    findings += _check_pending(store)
    findings += _check_adb_version()
    if deep:
        findings += _check_udev_permissions()
        findings += _check_android_toolchain()
        findings += _check_adb_conflicts()

    findings.sort(key=lambda finding: _SEVERITY_ORDER.get(finding.severity, 3))

    # One finding per scope: an "exported" device must not also be reported as
    # merely unattached, or the owner is given two commands for one problem.
    seen: set[str] = set()
    ordered: list[Finding] = []
    for finding in findings:
        if finding.scope and finding.scope in seen:
            continue
        if finding.scope:
            seen.add(finding.scope)
        ordered.append(finding)
    return ordered


def repair(finding: Finding) -> tuple[bool, str]:
    """Carry out a finding's fix, when Fenox is allowed to.

    Only `auto` findings are acted on. Anything needing administrator rights is
    refused here rather than attempted, so the hub can never wedge itself on a
    UAC prompt.
    """
    if not finding.auto or not finding.fix:
        return (False, "this one needs you to run it")
    log.info("repairing %s: %s", finding.id, finding.fix)
    if finding.id == "usbipd.not_attached":
        busid = finding.scope or ""
        ok, detail = usbipd.attach(busid)
        _record_attach_result(busid, ok, detail)
        if ok:
            log.info("attached %s to WSL", busid)
        else:
            log.warning("could not attach %s: %s", busid, _first_error(detail))
        return (ok, detail)
    return (False, "nothing Fenox can do for this one")


# --- keeping attachments alive ---------------------------------------------

#: How long to wait before retrying one busid. usbipd attach can take a few
#: seconds and a replug storm should not turn into a retry storm.
RETRY_COOLDOWN = 45.0

_last_attempt: dict[str, float] = {}

#: bus id -> the error text of the last failed attach, so `diagnose` can report a
#: stale export without itself attempting an attach.
_export_failures: dict[str, str] = {}

#: bus id -> the failure already reported at warning level, so an unfixable
#: condition is stated once rather than on every poll.
_reported_failures: dict[str, str] = {}


def _record_attach_result(busid: str, ok: bool, detail: str) -> None:
    if ok:
        _export_failures.pop(busid, None)
    else:
        _export_failures[busid] = detail or ""


def _cooldown_ok(busid: str, now: float) -> bool:
    return now - _last_attempt.get(busid, 0.0) >= RETRY_COOLDOWN


def repair_usbipd(now: float | None = None) -> list[str]:
    """Re-attach shared Android devices that WSL cannot currently see.

    This is what makes USB on WSL uneventful. A usbipd attachment does not
    survive a reboot, a device reset, or an unplug/replug, so the honest options
    are a command after every one of those or a loop that does it for you. Only
    devices that are already `Shared` are touched, so no administrator rights
    are involved and nothing is ever bound behind the owner's back.

    Returns the bus ids it acted on, for logging and tests.
    """
    import time

    if not host.IS_WSL or not usbipd.installed():
        return []

    moment = time.time() if now is None else now
    acted: list[str] = []

    for device in usbipd.android_devices():
        busid = device.busid
        if device.attached:
            _last_attempt.pop(busid, None)
            # Attached, so whatever went wrong last time is over; drop it so a
            # settled device cannot keep reporting a stale export.
            _export_failures.pop(busid, None)
            _reported_failures.pop(busid, None)
            continue
        # A device that is not shared cannot be attached without rights, and a
        # stale export will not clear itself; both are reported by `diagnose`.
        if not device.state.startswith(usbipd.STATE_SHARED):
            continue
        if not _cooldown_ok(busid, moment):
            continue

        _last_attempt[busid] = moment
        if _export_failures.get(busid) == "":
            # First attempt for this device, or it recovered since last time.
            log.info(
                "%s (%s) is shared with Windows but not attached to WSL; attaching it",
                device.display_name,
                busid,
            )
        ok, detail = usbipd.attach(busid)
        _record_attach_result(busid, ok, detail)
        if ok:
            log.info("attached %s to WSL", busid)
            acted.append(busid)
            continue

        reason = _first_error(detail)
        if _reported_failures.get(busid) == reason:
            # The same unfixable-by-us failure, over and over. A tool people
            # leave running must not fill the console with an identical line
            # every poll; it is still visible at debug level.
            log.debug("still cannot attach %s: %s", busid, reason)
            continue

        _reported_failures[busid] = reason
        log.warning("could not attach %s: %s", busid, reason)
        if "exported" in reason.lower():
            log.warning(
                "%s is held by a stale usbipd export and will not attach until it is "
                "cleared. In an Administrator PowerShell on Windows run: %s",
                busid,
                usbipd.unbind_command(busid),
            )
    return acted


def verify(finding: Finding, deep: bool = False) -> dict:
    """Act on a finding if allowed, then say whether it actually helped.

    A fix that is not checked is not a fix. Every action is therefore followed by
    a fresh diagnosis, and the result distinguishes four outcomes, which look
    identical from the outside:

    * **resolved** — the action worked and the problem is gone.
    * **escalated** — the action did not work, but it revealed the *real*, more
      specific blocker. Nothing is fixed, and the owner now has a better answer
      than the one they started with. This is reported as its own state precisely
      so it is never mistaken for success.
    * **unchanged** — the action ran and the same finding is still there.
    * **blocked** — the action could not even be attempted (it needed the owner).

    Returns the action outcome plus whatever findings remain.
    """
    ok, detail = repair(finding)
    after = diagnose(None, deep=deep)
    still_there = finding.id in {item.id for item in after}

    if not ok and finding.auto is False:
        state = "blocked"
    elif ok and not still_there:
        state = "resolved"
    elif not still_there:
        state = "escalated"
    else:
        state = "unchanged"

    return {
        "id": finding.id,
        "ok": ok,
        "state": state,
        "detail": detail,
        "remaining": [item.as_dict() for item in after],
        "blocking": [item.as_dict() for item in after if item.severity == ERROR],
    }


def auto_fixable() -> list[Finding]:
    """Every finding Fenox is allowed to act on, most urgent first."""
    return [finding for finding in diagnose(None, deep=False) if finding.auto]


def fix_all(deep: bool = False) -> list[dict]:
    """Run every automatic fix in turn, verifying each one.

    Deliberately one at a time: each action can change the diagnosis, so acting
    on a stale list is how a tool makes a machine worse while trying to help it.
    """
    results: list[dict] = []
    for finding in auto_fixable():
        results.append(verify(finding, deep=deep))
        if results[-1]["blocking"]:
            # Something blocking remains that Fenox cannot fix; further
            # automatic actions are unlikely to help and may be noise.
            break
    return results


def _first_error(detail: str) -> str:
    for line in str(detail or "").splitlines():
        if "error" in line.lower():
            return line.strip()
    return str(detail or "").strip().splitlines()[0] if str(detail or "").strip() else "no output"
