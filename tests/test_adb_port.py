from fenox.core import adb, host


def _fake_run(device_port: int, responded_ports: tuple[int, ...]):
    def run(args, timeout=None, cwd=None, env=None):
        port = int(args[args.index("-P") + 1])
        if port not in responded_ports:
            return host.Result(False, 1, "", "")
        text = "List of devices attached\n"
        if port == device_port:
            text += "15795455C8002334\tdevice\n"
        return host.Result(True, 0, text, "")

    return run


def test_detect_port_prefers_the_port_that_has_devices(monkeypatch):
    monkeypatch.setattr(adb, "_active_port", None)
    monkeypatch.delenv("FENOX_ADB_PORT", raising=False)
    monkeypatch.setattr(host, "adb_server_binary", lambda configured=None: "/usr/bin/adb")
    # The configured 5038 responds but has no devices; 5037 holds the phone.
    monkeypatch.setattr(host, "run", _fake_run(device_port=5037, responded_ports=(5037, 5038)))

    assert adb.detect_port(force=True) == 5037
    assert adb.current_port() == 5037


def test_detect_port_uses_the_configured_port_when_it_has_devices(monkeypatch):
    monkeypatch.setattr(adb, "_active_port", None)
    monkeypatch.setenv("FENOX_ADB_PORT", "5039")
    monkeypatch.setattr(host, "adb_server_binary", lambda configured=None: "/usr/bin/adb")
    monkeypatch.setattr(host, "run", _fake_run(device_port=5039, responded_ports=(5039,)))

    assert adb.detect_port(force=True) == 5039


def test_detect_port_falls_back_to_a_responding_port(monkeypatch):
    monkeypatch.setattr(adb, "_active_port", None)
    monkeypatch.delenv("FENOX_ADB_PORT", raising=False)
    monkeypatch.setattr(host, "adb_server_binary", lambda configured=None: "/usr/bin/adb")
    # No port has devices; 5037 at least responds, so it is preferred over 5038.
    monkeypatch.setattr(host, "run", _fake_run(device_port=-1, responded_ports=(5037,)))

    assert adb.detect_port(force=True) == 5037
