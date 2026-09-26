import json

from fenox.core import connect, env, host, report

PASSWORD = "a-strong-owner-password"


def _result(stdout: str) -> host.Result:
    return host.Result(True, 0, stdout, "")


# --- env: one source of truth ----------------------------------------------

def test_release_is_read_not_the_frozen_protocol_string(monkeypatch):
    """adb prints two numbers. Only one is the release.

    Two implementations of this existed and the product answered the question
    two ways: "Android Debug Bridge version 1.0.41" from the doctor, "36.0.0"
    from the connection layer.
    """
    monkeypatch.setattr(env, "_cache", {})
    out = "Android Debug Bridge version 1.0.41\nVersion 36.0.0-13206524\n"
    monkeypatch.setattr(env.host, "run", lambda *a, **k: _result(out))
    monkeypatch.setattr(env, "_resolve", lambda name, settings: "/usr/bin/adb")

    probed = env.tool("adb")

    assert probed.version == "36.0.0"
    assert probed.version_is_release is True


def test_prose_version_is_not_claimed_to_be_a_release(monkeypatch):
    monkeypatch.setattr(env, "_cache", {})
    out = "some-tool, a program that prints prose\n"
    monkeypatch.setattr(env.host, "run", lambda *a, **k: _result(out))
    monkeypatch.setattr(env, "_resolve", lambda name, settings: "/usr/bin/some-tool")

    probed = env.tool("some-tool")

    assert probed.version_is_release is False
    assert "prose" in probed.version


def test_tool_probes_are_cached(monkeypatch):
    monkeypatch.setattr(env, "_cache", {})
    calls = []
    monkeypatch.setattr(env, "_resolve", lambda name, settings: calls.append(name) or "/usr/bin/adb")
    monkeypatch.setattr(env.host, "run", lambda *a, **k: _result(""))

    env.tool("adb")
    env.tool("adb")
    assert calls == ["adb"]

    env.invalidate()
    env.tool("adb")
    assert calls == ["adb", "adb"]


def test_where_a_fix_runs_is_not_always_the_current_shell(monkeypatch):
    """On WSL the shell is bash but USB belongs to Windows."""
    monkeypatch.setattr(env.host, "IS_WSL", True)
    monkeypatch.setattr(env.host, "IS_WINDOWS", False)
    assert env.shell() == "posix"
    assert env.fix_runs_in() == "windows"

    monkeypatch.setattr(env.host, "IS_WSL", False)
    monkeypatch.setattr(env.host, "IS_WINDOWS", False)
    assert env.fix_runs_in() == "posix"


# --- redaction --------------------------------------------------------------

def test_home_and_account_names_are_masked(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "someone"))
    assert report.redact(f"{tmp_path}/someone/flutter/bin") == "~/flutter/bin"

    assert "someone" not in report.redact(r"C:\Users\someone\platform-tools")
    assert "someone" not in report.redact("/mnt/c/Users/someone/AppData")


def test_ip_addresses_are_masked_but_the_subnet_is_kept():
    """The subnet is the useful part when debugging a phone on the LAN."""
    masked = report.redact("phone at 192.168.1.42:37895")
    assert "192.168.1.x" in masked
    assert "42" not in masked


def test_serials_are_shortened():
    assert report._redact_serial("R3CR112R5CF") == "R3CR…"
    assert report._redact_serial("emulator-5554") == "emulator-5554"
    assert report._redact_serial("") == ""


# --- the report -------------------------------------------------------------

def _stub_environment(monkeypatch, *, findings=(), connected=(), tools=()):
    """Pin everything the report reads, so it is testable off a real machine."""
    monkeypatch.setattr(report.env, "adb_topology", lambda settings: env.AdbTopology(
        client="/usr/bin/adb",
        server="/usr/bin/adb",
        windows_exe="",
        configured_port=5038,
        active_port=5037,
        version="36.0.0",
        candidates=[],
    ))
    monkeypatch.setattr(report.env, "tools", lambda settings, refresh=False: [
        env.Tool(name=row[0], path=row[1], version=row[2], present=bool(row[1]), required=row[3])
        for row in tools
    ])

    def fake_checks(settings, store=None, deep=True):
        return {
            "tools": [probed.as_dict() for probed in report.env.tools(settings)],
            "notes": [],
            "findings": [finding.as_dict() for finding in findings],
            "connected": list(connected),
        }

    monkeypatch.setattr(report.doctor, "checks", fake_checks)
    monkeypatch.setattr(report, "_fenox_version", lambda: "0.1.0")


def test_a_clean_machine_reports_ok_and_exits_zero(monkeypatch):
    _stub_environment(monkeypatch)
    built = report.build({})
    rendered = report.render(built)

    assert built["ok"] is True
    assert "no problems found" in rendered
    assert "Summary: 0 error(s)" in rendered


def test_a_warning_never_reads_as_all_clear(monkeypatch):
    """A headline that says "no problems" above a list of warnings is a lie."""
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(id="usbipd.not_attached", severity=connect.WARN, title="t", detail="d", auto=True)],
    )
    built = report.build({})

    rendered = report.render(built)

    assert "no problems found" not in rendered
    assert "1 warning" in rendered.splitlines()[0]


def test_errors_are_counted_and_change_the_verdict(monkeypatch):
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(id="usbipd.missing", severity=connect.ERROR, title="t", detail="d")],
    )
    built = report.build({})

    assert built["ok"] is False
    assert "1 problem need" in report.render(built).splitlines()[0]


def test_prose_steps_are_not_rendered_as_commands(monkeypatch):
    """Rendering "or download …" with a $ in front tells the reader to run it."""
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(
            id="adb.too_old", severity=connect.INFO, title="t", detail="d",
            fix='sdkmanager --install "platform-tools"',
            also=["or download from developer.android.com"],
        )],
    )

    rendered = report.render(report.build({}))

    assert "$ sdkmanager --install" in rendered
    assert "$ or download" not in rendered
    assert "or download from developer.android.com" in rendered


def test_windows_fixes_say_where_to_run_them(monkeypatch):
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(
            id="usbipd.unbound", severity=connect.ERROR, title="t", detail="d",
            fix="usbipd bind --busid 1-2", runs_in="windows",
        )],
    )

    rendered = report.render(report.build({}))

    assert "Administrator PowerShell on Windows" in rendered


def test_connected_devices_are_redacted_by_default(monkeypatch):
    _stub_environment(monkeypatch, connected=["R3CR112R5CF"])

    assert report.build({})["connected"] == ["R3CR…"]
    assert report.build({}, redact_output=False)["connected"] == ["R3CR112R5CF"]


def test_paths_are_redacted_by_default(monkeypatch, tmp_path):
    home = tmp_path / "someone"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _stub_environment(monkeypatch, tools=[("adb", f"{home}/platform-tools/adb", "36.0.0", True)])

    redacted = [row for row in report.build({})["tools"] if row["name"] == "adb"][0]
    full = [row for row in report.build({}, redact_output=False)["tools"] if row["name"] == "adb"][0]

    assert redacted["path"] == "~/platform-tools/adb"
    assert full["path"] == f"{home}/platform-tools/adb"


def test_report_is_json_serialisable(monkeypatch):
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(id="adb.missing", severity=connect.ERROR, title="t", detail="d", fix="apt install adb")],
    )
    built = report.build({})

    assert json.loads(json.dumps(built))["problems"][0]["id"] == "adb.missing"


def test_advice_alone_does_not_fail_the_report(monkeypatch):
    """An out-of-date adb is worth mentioning, not a broken machine."""
    _stub_environment(
        monkeypatch,
        findings=[connect.Finding(id="adb.too_old", severity=connect.INFO, title="t", detail="d")],
    )
    built = report.build({})

    assert built["ok"] is True
    assert built["counts"]["info"] == 1


def test_a_fresh_machine_with_nothing_installed_fails_the_report(monkeypatch):
    """The regression CI guards: a bare machine must not be reported as healthy.

    This is the case that used to print every tool as `ok` and claim USB devices
    were visible, and it is why `fenox doctor` now has a non-zero exit code.
    """
    monkeypatch.setattr(report.env, "adb_topology", lambda settings: env.AdbTopology(
        client="", server="", windows_exe="", configured_port=5038, active_port=None,
        version="", candidates=[],
    ))
    monkeypatch.setattr(report.env, "tools", lambda settings, refresh=False: [])
    monkeypatch.setattr(report.env, "tool", lambda name, settings=None, refresh=False: env.Tool(
        name=name, path="", version="", present=False, required=True,
    ))
    # The engine asks adb directly whether it can be found, so that has to be
    # stubbed too or it reports the real machine rather than the imaginary one.
    monkeypatch.setattr(connect.adb, "_client", lambda: None)
    monkeypatch.setattr(connect.adb, "_active_port", None)
    monkeypatch.setattr(connect.adb, "client_version", lambda: "")
    monkeypatch.setattr(connect.adb, "_run", lambda args, timeout=10: _result("List of devices attached\n"))
    monkeypatch.setattr(connect.host, "IS_WSL", False)
    monkeypatch.setattr(connect, "_check_android_toolchain", lambda: [])
    monkeypatch.setattr(connect, "_check_udev_permissions", lambda: [])

    built = report.build({})

    assert built["ok"] is False
    assert built["counts"]["error"] >= 1
    assert any(problem["id"] == "adb.missing" for problem in built["problems"])
    assert "problem" in report.render(built).splitlines()[0]


def test_the_headline_agrees_with_the_error_count(monkeypatch):
    for count, verb in ((1, "needs"), (2, "need")):
        _stub_environment(
            monkeypatch,
            findings=[
                connect.Finding(id=f"problem{index}", severity=connect.ERROR, title="t", detail="d")
                for index in range(count)
            ],
        )
        headline = report.render(report.build({})).splitlines()[0]
        assert f"{count} problem" in headline
        assert verb in headline


# --- bind address -----------------------------------------------------------

def test_environment_variables_are_honoured(monkeypatch, tmp_path):
    """The Docker image sets FENOX_HOST/FENOX_PORT; they must not be ignored.

    An image that declares `FENOX_HOST=0.0.0.0` and then binds loopback only
    fails after deployment, which is the worst place to find out.
    """
    import argparse

    from fenox.cli import main as cli

    monkeypatch.setenv("FENOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FENOX_HOST", "0.0.0.0")
    monkeypatch.setenv("FENOX_PORT", "9999")

    host, port = cli._resolve_bind(argparse.Namespace(host=None, port=None))

    assert host == "0.0.0.0"
    assert port == 9999


def test_explicit_flags_beat_the_environment(monkeypatch, tmp_path):
    import argparse

    from fenox.cli import main as cli

    monkeypatch.setenv("FENOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FENOX_HOST", "0.0.0.0")
    monkeypatch.setenv("FENOX_PORT", "9999")

    host, port = cli._resolve_bind(argparse.Namespace(host="127.0.0.1", port=1234))

    assert (host, port) == ("127.0.0.1", 1234)


def test_a_nonsense_port_falls_back_instead_of_crashing(monkeypatch, tmp_path):
    import argparse

    from fenox.cli import main as cli

    monkeypatch.setenv("FENOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FENOX_PORT", "not-a-port")

    _, port = cli._resolve_bind(argparse.Namespace(host=None, port=None))

    assert port == 8787


# --- conflicting adb installations ------------------------------------------

def test_conflicting_adb_versions_are_reported(monkeypatch):
    """Two adbs of different versions fight over one device.

    The symptom is a phone that connects and then vanishes, which points nowhere
    near the real cause, so the report has to name it.
    """
    monkeypatch.setattr(connect.env, "conflicting_adbs", lambda settings=None: [
        {"path": "/opt/platform-tools/adb", "version": "35.0.2", "is_release": True},
    ])
    monkeypatch.setattr(connect.env, "adb_topology", lambda settings=None: env.AdbTopology(
        client="/usr/local/bin/adb", server="/usr/local/bin/adb", windows_exe="",
        configured_port=5038, active_port=5037, version="36.0.0", candidates=[],
    ))
    monkeypatch.setattr(connect.env, "tool", lambda name, settings=None, refresh=False: env.Tool(
        name="flutter", path="", version="", present=False, required=True,
    ))

    findings = connect._check_adb_conflicts()

    assert len(findings) == 1
    assert findings[0].id == "adb.conflicting_installations"
    assert findings[0].severity == connect.WARN
    assert "35.0.2" in findings[0].detail
    assert "36.0.0" in findings[0].detail


def test_matching_adb_versions_are_not_worth_reporting(monkeypatch):
    """Four identical installs are unusual but not a problem worth shouting about."""
    monkeypatch.setattr(connect.env, "conflicting_adbs", lambda settings=None: [])

    assert connect._check_adb_conflicts() == []


def test_probing_failures_do_not_break_diagnosis(monkeypatch):
    """A diagnostic that raises when the machine is odd is worse than none."""
    def boom(settings=None):
        raise OSError("adb exploded")

    monkeypatch.setattr(connect.env, "conflicting_adbs", boom)

    assert connect._check_adb_conflicts() == []
