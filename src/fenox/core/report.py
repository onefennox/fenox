"""The support report: one artefact that answers "is this machine working?".

Built as data rather than printed inline, so the same content can be rendered for
a terminal, serialised as JSON for a bug tracker, or shown in the web app, and so
it can be asserted on in tests.

Redaction is the default and is not optional-by-accident. A report gets pasted
into a forum, so home directories, account names, device identifiers and network
addresses are all masked. `--full` turns that off for reading on your own
machine; secrets are never included either way, because they are not needed to
diagnose anything here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from . import connect, doctor, env, host, usbipd

#: A serial is a device identifier: enough to recognise your own phone in a log,
#: not enough to identify it to a reader.
_SERIAL = re.compile(r"\b([A-Z0-9]{6,12})\b")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


def redact(text: str, home: str | None = None) -> str:
    """Mask the things in a string that should not leave the machine."""
    if not text:
        return text
    root = home or str(Path.home())
    out = text.replace(root, "~")
    # /mnt/c/Users/<name> is the Windows account on WSL.
    out = re.sub(r"([A-Za-z]:\\Users\\)[^\\\s\"']+", r"\1<user>", out)
    out = re.sub(r"(/mnt/[a-z]/Users/)[^/\s\"']+", r"\1<user>", out)
    out = _IPV4.sub(lambda m: f"{m.group(1)}.{m.group(2)}.{m.group(3)}.x", out)
    return out


def _redact_serial(serial: str) -> str:
    serial = (serial or "").strip()
    if not serial:
        return ""
    if serial.startswith("emulator-"):
        return serial
    return serial[:4] + "…" if len(serial) > 4 else "…"


def build(settings: dict | None = None, store=None, redact_output: bool = True, deep: bool = True) -> dict:
    """Assemble the report as data.

    `ok` is false only for findings that actually stop a device being usable.
    Advice and upgrades are reported without failing the report, so a machine
    with an out-of-date adb is not described as broken.

    `deep` includes the slow checks (`flutter doctor`, udev permissions). A
    report is worth paying for; a dashboard poll is not.
    """
    settings = settings or {}
    topology = env.adb_topology(settings)
    checks = doctor.checks(settings, store=store, deep=deep)
    findings = [connect.Finding(**_finding_kwargs(row)) for row in checks["findings"]]
    blocking = [finding for finding in findings if finding.severity == connect.ERROR]

    connected = [_redact_serial(device) if redact_output else device for device in checks["connected"]]

    problems = []
    for finding in findings:
        row = finding.as_dict()
        if redact_output:
            row["title"] = redact(row["title"])
            row["detail"] = redact(row["detail"])
            if row.get("fix"):
                row["fix"] = redact(row["fix"])
            row["also"] = [redact(step) for step in row["also"]]
        problems.append(row)

    usbipd_state = None
    if host.IS_WSL:
        usbipd_state = {
            "installed": usbipd.installed(),
            "version": usbipd.version(),
            "attached": sorted(device.busid for device in usbipd.list_devices() if device.attached),
            "shared": sorted(device.busid for device in usbipd.list_devices() if device.shared and not device.attached),
        }

    return {
        "ok": not blocking,
        "version": _fenox_version(),
        "platform": host.HOST.os,
        "python": sys.version.split()[0],
        "redacted": redact_output,
        "problems": problems,
        "counts": {
            "error": len([f for f in findings if f.severity == connect.ERROR]),
            "warn": len([f for f in findings if f.severity == connect.WARN]),
            "info": len([f for f in findings if f.severity == connect.INFO]),
        },
        "tools": [
            {
                "name": row["name"],
                "present": row["present"],
                "required": row["required"],
                "version": row["version"],
                "path": (redact(row["path"]) if redact_output else row["path"]),
            }
            for row in checks["tools"]
        ],
        "adb": {
            "version": topology.version,
            "client": redact(topology.client) if redact_output else topology.client,
            "server": redact(topology.server) if redact_output else topology.server,
            "configured_port": topology.configured_port,
            "active_port": topology.active_port,
        },
        "connected": connected,
        "notes": [redact(note["text"]) if redact_output else note["text"] for note in checks["notes"]],
        "usbipd": usbipd_state,
    }


def _finding_kwargs(row: dict) -> dict:
    return {
        "id": row["id"],
        "severity": row["severity"],
        "title": row["title"],
        "detail": row["detail"],
        "fix": row.get("fix"),
        "auto": row.get("auto", False),
        "scope": row.get("scope"),
        "also": row.get("also") or [],
        "runs_in": row.get("runs_in", "here"),
    }


def _fenox_version() -> str:
    from ..version import __version__

    return __version__


# --- rendering --------------------------------------------------------------

def _verdict(report: dict) -> str:
    """A headline that cannot contradict the body.

    The first version of this printed "OK — no problems found" and then, three
    lines later, listed a warning about the phone being unusable. A headline that
    overclaims is worse than no headline, so the wording tracks the counts
    exactly: `ok` (the exit-code meaning, errors only) is reported separately
    from "is there anything to read".
    """
    counts = report["counts"]
    if counts["error"]:
        plural = "" if counts["error"] == 1 else "s"
        verb = "needs" if counts["error"] == 1 else "need"
        return f"{counts['error']} problem{plural} {verb} fixing"
    if counts["warn"]:
        plural = "" if counts["warn"] == 1 else "s"
        return f"nothing blocking, {counts['warn']} warning{plural} to read"
    if counts["info"]:
        plural = "" if counts["info"] == 1 else "s"
        return f"nothing blocking, {counts['info']} note{plural}"
    return "no problems found"


_LABEL = {connect.ERROR: "ERROR", connect.WARN: "WARN", connect.INFO: "INFO"}

_WHERE = {"windows": "in an Administrator PowerShell on Windows", "here": "in your terminal"}


def _is_command(text: str) -> bool:
    """Whether a step is a command to paste, or prose that follows it.

    `also` holds both — "then: usbipd bind" and "or download the latest Platform
    Tools" — and rendering prose with a `$` in front tells the reader to run it.
    """
    stripped = str(text or "").strip()
    if not stripped:
        return False
    head = stripped.split()[0].lower()
    return head in {"usbipd", "adb", "sdkmanager", "flutter", "scrcpy", "sudo", "winget", "brew", "apt", "curl", "wsl"} or "=" in stripped.split()[0]


def render(report: dict, width: int = 78) -> str:
    """Plain text, no colour, safe to paste anywhere."""
    lines: list[str] = []
    add = lines.append

    verdict = _verdict(report)
    add(f"fenox {report['version']} — {verdict}")
    add(f"platform {report['platform']} · python {report['python']}")
    add("")

    if report["problems"]:
        add("Problems")
        for problem in report["problems"]:
            add(f"  [{_LABEL.get(problem['severity'], 'INFO'):5}] {problem['title']}")
            for line in _wrap(problem["detail"], width - 4):
                add(f"          {line}")
            steps = [step for step in [problem.get("fix"), *problem["also"]] if step]
            if steps:
                add(f"          fix — {_WHERE.get(problem.get('runs_in', 'here'), 'in your terminal')}:")
                for step in steps:
                    add(f"            $ {step}" if _is_command(step) else f"            {step}")
            if problem.get("auto"):
                add("          fenox can do this one itself")
            if problem.get("scope"):
                add(f"          device: {problem['scope']}")
            add("")
    else:
        add("No connection problems found.")
        add("")

    counts = report["counts"]
    add(f"Summary: {counts['error']} error(s), {counts['warn']} warning(s), {counts['info']} note(s)")
    add("")

    add("Tools")
    for tool in report["tools"]:
        state = "ok     " if tool["present"] else ("missing" if tool["required"] else "optional")
        version = tool["version"] or "-"
        add(f"  [{state}] {tool['name']:<10} {version:<24} {tool['path']}")
    add("")

    adb_info = report["adb"]
    add("adb")
    add(f"  release     : {adb_info['version'] or '-'}")
    add(f"  client      : {adb_info['client'] or '-'}")
    add(f"  server      : {adb_info['server'] or '-'}")
    add(f"  port        : configured {adb_info['configured_port']}, active {adb_info['active_port']}")
    add(f"  devices     : {', '.join(report['connected']) if report['connected'] else 'none'}")
    if report.get("usbipd"):
        state = report["usbipd"]
        add("")
        add("usbipd (WSL USB bridge)")
        add(f"  installed   : {state['installed']} {state['version']}".rstrip())
        add(f"  attached    : {', '.join(state['attached']) or '-'}")
        add(f"  shared only : {', '.join(state['shared']) or '-'}")
    if report["notes"]:
        add("")
        add("Notes")
        for note in report["notes"]:
            for line in _wrap(note, width - 2):
                add(f"  {line}")
    add("")
    if report["redacted"]:
        add("Identifiers and addresses are masked. Re-run with --full to see them.")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
