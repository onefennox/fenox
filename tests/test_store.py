import json
from pathlib import Path

from fenox.core.config import Store


def test_defaults_are_present_on_first_load(tmp_path):
    store = Store(tmp_path).load()
    assert store.settings["reach"] == "local"
    assert store.settings["port"] == 8787
    assert store.devices() == {}
    assert store.projects() == {}


def test_settings_persist_across_reopen(tmp_path):
    store = Store(tmp_path).load()
    store.settings["remote_domain"] = "example.test"
    reopened = Store(tmp_path).load()
    assert reopened.settings["remote_domain"] == "example.test"


def test_devices_projects_and_groups_round_trip(tmp_path):
    store = Store(tmp_path).load()
    store.upsert_device("pixel", {"type": "usb", "serial": "ABC123", "model": "Pixel 7"})
    store.upsert_project("demo", {"path": "/srv/demo", "port": "8080"})
    store.set_group("phones", ["pixel"])

    reopened = Store(tmp_path).load()
    assert reopened.device("pixel")["serial"] == "ABC123"
    assert reopened.project("demo")["path"] == "/srv/demo"
    assert reopened.groups() == {"phones": ["pixel"]}

    reopened.delete_device("pixel")
    reopened.delete_project("demo")
    assert reopened.devices() == {}
    assert reopened.projects() == {}


def test_legacy_config_is_imported_once(tmp_path):
    legacy = Path.home() / ".fenox.json"
    legacy.write_text(json.dumps({
        "apps": {"demo": {"path": "/srv/demo", "port": "4000", "ws_local": "ws://localhost:4000"}},
        "devices": {"phone": {"ip": "192.168.1.5", "port": "5555"}},
        "settings": {"remote_domain": "legacy.test"},
    }))

    store = Store(tmp_path).load()
    assert store.projects()["demo"]["path"] == "/srv/demo"
    # The legacy websocket field is renamed to the current schema.
    assert store.projects()["demo"]["socket_local"] == "ws://localhost:4000"
    assert "ws_local" not in store.projects()["demo"]
    assert store.devices()["phone"]["ip"] == "192.168.1.5"
    # The legacy schema left `type` implicit; wireless is inferred from the IP.
    assert store.devices()["phone"]["type"] == "wireless"
    assert store.settings["remote_domain"] == "legacy.test"

    # The legacy file is left in place, and a second start does not re-import.
    assert legacy.exists()
    store.delete_device("phone")
    Store(tmp_path).load()
    assert store.devices() == {}


def test_run_history_is_recorded(tmp_path):
    store = Store(tmp_path).load()
    store.log_run("demo", "pixel", "local", ok=True)
    store.log_run("demo", "pixel", "build", ok=False)
    runs = store.recent_runs()
    assert len(runs) == 2
    assert {run["status"] for run in runs} == {"ok", "failed"}
