from fenox.core import adb, connect, usbipd

# --- usbipd output parsing --------------------------------------------------

LIST = """Connected:
BUSID  VID:PID    DEVICE                                       STATE
1-2    04e8:6864  SAMSUNG Mobile USB Remote NDIS Network Device  Shared
1-5    17ef:f006  USB Input Device                              Not shared
1-8    04f2:b7fa  Integrated Camera, Integrated IR Camera       Attached

Persisted:
GUID                                  DEVICE
1dae7258-2c19-49dd-8fe4-874c1e0af448  Tenithan, SAMSUNG Mobile USB Modem #2
"""


def test_parse_list_reads_state_names_and_ids():
    devices, _ = usbipd.parse_list(LIST)
    by_busid = {device.busid: device for device in devices}

    assert set(by_busid) == {"1-2", "1-5", "1-8"}
    assert by_busid["1-2"].vid_pid == "04e8:6864"
    assert by_busid["1-2"].name == "SAMSUNG Mobile USB Remote NDIS Network Device"
    assert by_busid["1-2"].state == "Shared"


def test_not_shared_is_one_state_not_a_name_suffix():
    """"Not shared" is two words; taking the last token turned it into "shared"."""
    devices, _ = usbipd.parse_list(LIST)
    by_busid = {device.busid: device for device in devices}

    assert by_busid["1-5"].state == "Not shared"
    assert by_busid["1-5"].name == "USB Input Device"
    assert by_busid["1-5"].shared is False
    assert by_busid["1-5"].attached is False


def test_state_predicates():
    devices, _ = usbipd.parse_list(LIST)
    by_busid = {device.busid: device for device in devices}

    assert by_busid["1-2"].shared is True
    assert by_busid["1-2"].attached is False
    assert by_busid["1-8"].attached is True
    assert by_busid["1-8"].shared is True


def test_composite_device_names_keep_their_commas():
    devices, _ = usbipd.parse_list(LIST)
    camera = next(device for device in devices if device.busid == "1-8")

    assert camera.name == "Integrated Camera, Integrated IR Camera"
    assert camera.display_name == "Integrated Camera"


def test_android_detection_uses_the_vendor_id():
    devices, _ = usbipd.parse_list(LIST)
    by_busid = {device.busid: device for device in devices}

    assert by_busid["1-2"].android is True
    assert by_busid["1-5"].android is False


def test_parse_list_survives_crlf_and_junk():
    noisy = LIST.replace("\n", "\r\n") + "\r\nnot a row at all\r\n"
    devices, _ = usbipd.parse_list(noisy)

    assert [device.busid for device in devices] == ["1-2", "1-5", "1-8"]


def test_parse_list_of_nothing_is_empty():
    assert usbipd.parse_list("") == ([], {})
    assert usbipd.parse_list("Connected:\nBUSID  VID:PID  DEVICE  STATE\n") == ([], {})


# --- mDNS -------------------------------------------------------------------

MDNS = """List of discovered mdns services
adb-ABC123\t_adb-tls-pairing._tcp\t192.168.1.20:41234
adb-ABC123\t_adb-tls-connect._tcp\t192.168.1.20:37895
legacy-phone\t_adb._tcp\t192.168.1.30:5555
"""


def test_mdns_finds_pairing_connect_and_legacy(monkeypatch):
    monkeypatch.setattr(adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": MDNS, "stderr": ""})())

    kinds = {service["kind"] for service in adb.mdns_services()}

    assert kinds == {"pairing", "connect", "legacy"}


def test_mdns_exposes_pairing_candidates(monkeypatch):
    """A phone showing a pairing code publishes _adb-tls-pairing only.

    This is the moment the owner is staring at a six-digit code, so failing to
    discover it is what forces the IP/port form.
    """
    monkeypatch.setattr(adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": MDNS, "stderr": ""})())

    pairing = adb.mdns_pairing_candidates()

    assert len(pairing) == 1
    assert pairing[0]["ip"] == "192.168.1.20"
    assert pairing[0]["port"] == "41234"


def test_mdns_candidates_only_returns_connectable(monkeypatch):
    monkeypatch.setattr(adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": MDNS, "stderr": ""})())

    assert adb.mdns_candidates() == [("192.168.1.20", "37895")]


def test_mdns_port_finds_a_connect_service(monkeypatch):
    monkeypatch.setattr(adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": MDNS, "stderr": ""})())

    assert adb.mdns_port("192.168.1.20") == "37895"
    assert adb.mdns_port("192.168.1.99") is None


def test_client_version_prefers_the_release_line(monkeypatch):
    """"Android Debug Bridge version 1.0.41" is frozen; the release is 36.0.0."""
    out = "Android Debug Bridge version 1.0.41\nVersion 36.0.0-13206524\n"
    monkeypatch.setattr(adb, "_version_cache", None)
    monkeypatch.setattr(adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": out, "stderr": ""})())

    assert adb.client_version() == "36.0.0"


# --- diagnosis --------------------------------------------------------------

def _device(busid="1-2", state="Shared", vid_pid="04e8:6864", name="Samsung Phone", persisted=None):
    return usbipd.UsbipdDevice(
        busid=busid, vid_pid=vid_pid, name=name, state=state, persisted=list(persisted or [])
    )


def _prepare(monkeypatch, *, wsl=True, installed=True, devices=(), attached_ok=True, attach_detail="", adb_version="36.0.0", export_failures=None):
    monkeypatch.setattr(connect.host, "IS_WSL", wsl)
    monkeypatch.setattr(connect.usbipd, "installed", lambda: installed)
    monkeypatch.setattr(connect.usbipd, "list_devices", lambda: list(devices))
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [d for d in devices if d.android])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: (attached_ok, attach_detail))
    monkeypatch.setattr(connect.adb, "_client", lambda: "/usr/bin/adb")
    monkeypatch.setattr(connect.adb, "_active_port", 5037)
    monkeypatch.setattr(connect.adb, "_run", lambda args, timeout=10: type("R", (), {"stdout": "List of devices attached\n", "stderr": ""})())
    monkeypatch.setattr(connect.adb, "client_version", lambda: adb_version)
    monkeypatch.setattr(connect, "_export_failures", dict(export_failures or {}))
    monkeypatch.setattr(connect, "_reported_failures", {})


def test_wsl_without_usbipd_says_so_and_offers_the_install(monkeypatch):
    _prepare(monkeypatch, installed=False)

    finding = next(f for f in connect.diagnose() if f.id == "usbipd.missing")

    assert finding.severity == connect.ERROR
    assert "winget install" in (finding.fix or "")
    assert finding.auto is False  # needs administrator rights


def test_a_shared_phone_fenox_can_attach_is_marked_auto(monkeypatch):
    _prepare(monkeypatch, devices=[_device()])

    finding = next(f for f in connect.diagnose() if f.id == "usbipd.not_attached")

    assert finding.auto is True
    assert finding.fix == "usbipd attach --wsl --busid 1-2"
    assert "does not survive a reboot" in finding.detail


def test_an_unshared_phone_needs_the_owner_to_bind(monkeypatch):
    _prepare(monkeypatch, devices=[_device(state="Not shared")])

    finding = next(f for f in connect.diagnose() if f.id == "usbipd.unbound")

    assert finding.auto is False
    assert finding.fix == "usbipd bind --busid 1-2"
    assert "survives reboots" in finding.detail


def test_diagnose_never_attaches_anything(monkeypatch):
    """A read-only question must not change the machine.

    Diagnosing used to call `usbipd attach` to test for a stale export, which
    meant every dashboard poll tried to re-attach the phone.
    """
    calls = []
    _prepare(monkeypatch, devices=[_device()])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))

    connect.diagnose()

    assert calls == []


def test_stale_export_is_reported_once_with_the_full_remedy(monkeypatch):
    _prepare(
        monkeypatch,
        devices=[_device(persisted=["SAMSUNG Mobile USB Remote NDIS Network Device"])],
        export_failures={"1-2": "WSL usbip: error: Attach Request for 1-2 failed - Device busy (exported)"},
    )

    findings = connect.diagnose()
    finding = next(f for f in findings if f.id == "usbipd.stale_export")

    assert finding.severity == connect.ERROR
    assert finding.fix == "usbipd unbind --busid 1-2"
    assert "usbipd bind --busid 1-2" in finding.also
    # The same device must not also be reported as merely "needs attaching",
    # or the owner is given two commands for one problem.
    assert not [f for f in findings if f.id == "usbipd.not_attached"]
    assert "1 saved auto-attach entry" in finding.detail


def test_a_failed_attach_is_what_reveals_a_stale_export(monkeypatch):
    """The loop tries first; the finding appears from the failure it records."""
    _prepare(monkeypatch, devices=[_device()], attached_ok=False,
             attach_detail="Attach Request for 1-2 failed - Device busy (exported)")
    monkeypatch.setattr(connect, "_last_attempt", {})
    monkeypatch.setattr(connect, "_export_failures", {})

    # Before the attempt there is nothing to report beyond "not attached".
    assert next(f for f in connect.diagnose() if f.scope == "1-2").id == "usbipd.not_attached"

    connect.repair_usbipd(now=1000.0)

    finding = next(f for f in connect.diagnose() if f.scope == "1-2")
    assert finding.id == "usbipd.stale_export"
    assert finding.auto is False  # now it needs the owner


def test_a_successful_attach_clears_a_previous_export_failure(monkeypatch):
    _prepare(monkeypatch, devices=[_device(state="Attached")], attached_ok=True)
    monkeypatch.setattr(connect, "_export_failures", {"1-2": "Device busy (exported)"})

    connect.repair_usbipd(now=1000.0)  # already attached: clears the memory

    assert connect._export_failures == {}


def test_an_attached_phone_raises_no_usbipd_finding(monkeypatch):
    _prepare(monkeypatch, devices=[_device(state="Attached")])

    assert not [f for f in connect.diagnose() if f.id.startswith("usbipd-")]


def test_non_android_devices_are_left_alone(monkeypatch):
    _prepare(monkeypatch, devices=[_device(vid_pid="17ef:f006", name="USB Input Device")])

    assert not [f for f in connect.diagnose() if f.id.startswith("usbipd-")]


def test_native_linux_never_mentions_usbipd(monkeypatch):
    _prepare(monkeypatch, wsl=False, devices=[_device(state="Not shared")])

    assert not [f for f in connect.diagnose() if f.id.startswith("usbipd-")]


def test_old_platform_tools_is_suggested_but_not_an_error(monkeypatch):
    _prepare(monkeypatch, adb_version="36.0.0")

    finding = next(f for f in connect.diagnose() if f.id == "adb.too_old")

    assert finding.severity == connect.INFO
    assert "Wi-Fi 2.0" in finding.detail


def test_current_platform_tools_is_not_mentioned(monkeypatch):
    _prepare(monkeypatch, adb_version="37.0.0")

    assert not [f for f in connect.diagnose() if f.id == "adb.too_old"]


def test_findings_are_ordered_most_severe_first(monkeypatch):
    _prepare(monkeypatch, installed=False, adb_version="36.0.0")

    severities = [finding.severity for finding in connect.diagnose()]

    assert severities == sorted(severities, key=lambda level: connect._SEVERITY_ORDER[level])


def test_unauthorized_device_is_explained(monkeypatch):
    _prepare(monkeypatch)
    monkeypatch.setattr(
        connect.adb,
        "_run",
        lambda args, timeout=10: type("R", (), {"stdout": "List of devices attached\nR3CR  unauthorized\n", "stderr": ""})(),
    )

    finding = next(f for f in connect.diagnose() if f.id == "device.unauthorized")

    assert "Allow USB debugging" in finding.detail


# --- acting on a finding ----------------------------------------------------

def test_repair_refuses_anything_needing_the_owner(monkeypatch):
    called = []
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: called.append(busid) or (True, ""))

    ok, detail = connect.repair(connect.Finding(id="usbipd.unbound", severity="error", title="t", detail="d",
                                               fix="usbipd bind --busid 1-2"))

    assert ok is False
    assert called == []
    assert "you to run it" in detail


def test_repair_attaches_an_auto_finding(monkeypatch):
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: (True, "attached"))
    finding = connect.Finding(
        id="usbipd.not_attached",
        severity="warn",
        title="t",
        detail="d",
        fix="usbipd attach --wsl --busid 1-2",
        auto=True,
        scope="1-2",
    )

    ok, _ = connect.repair(finding)

    assert ok is True


# --- keeping attachments alive ---------------------------------------------

def test_repair_attaches_a_shared_phone_on_its_own(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.host, "IS_WSL", True)
    monkeypatch.setattr(connect.usbipd, "installed", lambda: True)
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [_device()])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))
    monkeypatch.setattr(connect, "_last_attempt", {})

    assert connect.repair_usbipd(now=1000.0) == ["1-2"]
    assert calls == ["1-2"]


def test_repair_does_nothing_off_wsl(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.host, "IS_WSL", False)
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [_device()])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))

    assert connect.repair_usbipd(now=1000.0) == []
    assert calls == []


def test_repair_never_touches_an_unshared_device(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.host, "IS_WSL", True)
    monkeypatch.setattr(connect.usbipd, "installed", lambda: True)
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [_device(state="Not shared")])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))

    assert connect.repair_usbipd(now=1000.0) == []
    assert calls == []


def test_repair_leaves_an_attached_phone_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.host, "IS_WSL", True)
    monkeypatch.setattr(connect.usbipd, "installed", lambda: True)
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [_device(state="Attached")])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))

    assert connect.repair_usbipd(now=1000.0) == []
    assert calls == []


def test_repair_waits_out_the_cooldown(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.host, "IS_WSL", True)
    monkeypatch.setattr(connect.usbipd, "installed", lambda: True)
    monkeypatch.setattr(connect.usbipd, "android_devices", lambda: [_device()])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))
    monkeypatch.setattr(connect, "_last_attempt", {})

    connect.repair_usbipd(now=1000.0)
    connect.repair_usbipd(now=1001.0)  # a second poll, moments later
    assert calls == ["1-2"]

    connect.repair_usbipd(now=1000.0 + connect.RETRY_COOLDOWN + 1)
    assert calls == ["1-2", "1-2"]


# --- the route --------------------------------------------------------------

PASSWORD = "a-strong-owner-password"


def _client(tmp_path):
    from fastapi.testclient import TestClient

    from fenox.server.app import create_app

    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_connection_route_requires_authentication(tmp_path):
    from fastapi.testclient import TestClient

    from fenox.server.app import create_app

    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    try:
        assert client.get("/api/system/connection").status_code in (401, 403)
    finally:
        client.__exit__(None, None, None)


def test_connection_route_reports_findings_and_environment(tmp_path, monkeypatch):
    _prepare(monkeypatch, devices=[_device()], adb_version="36.0.0")
    monkeypatch.setattr(connect.usbipd, "version", lambda: "5.3.0")
    monkeypatch.setattr(connect.adb, "mdns_pairing_candidates", lambda: [{"kind": "pairing", "ip": "10.0.0.5", "port": "1", "name": "x"}])
    monkeypatch.setattr(connect.adb, "mdns_candidates", lambda: [("10.0.0.5", "2")])

    client = _client(tmp_path)
    try:
        body = client.get("/api/system/connection").json()

        assert [finding["id"] for finding in body["findings"]] == ["usbipd.not_attached", "adb.too_old"]
        assert body["findings"][0]["auto"] is True
        assert body["wireless"]["pairing"][0]["ip"] == "10.0.0.5"
        assert body["wireless"]["connect"] == [["10.0.0.5", "2"]]
        assert body["adb_version"] == "36.0.0"
        assert body["usbipd"]["installed"] is True
    finally:
        client.__exit__(None, None, None)


def test_repair_route_acts_only_on_a_known_finding(tmp_path, monkeypatch):
    calls = []
    _prepare(monkeypatch, devices=[_device()])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, "attached"))

    client = _client(tmp_path)
    try:
        ok = client.post("/api/system/connection/repair", json={"id": "usbipd.not_attached"}).json()
        assert ok["ok"] is True
        assert calls == ["1-2"]

        assert client.post("/api/system/connection/repair", json={"id": "nope"}).status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_repair_route_refuses_a_finding_the_owner_must_run(tmp_path, monkeypatch):
    calls = []
    _prepare(monkeypatch, devices=[_device(state="Not shared")])
    monkeypatch.setattr(connect.usbipd, "attach", lambda busid: calls.append(busid) or (True, ""))

    client = _client(tmp_path)
    try:
        body = client.post("/api/system/connection/repair", json={"id": "usbipd.unbound"}).json()

        assert body["ok"] is False
        assert calls == []
    finally:
        client.__exit__(None, None, None)

