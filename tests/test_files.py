from fastapi.testclient import TestClient

from fenox.core import devices, files
from fenox.server.app import create_app

PASSWORD = "a-strong-owner-password"


def test_ls_parsing_sorts_directories_and_handles_names_with_spaces():
    output = "\n".join([
        "total 12",
        "drwxrwx--x 2 u0_a1 ext_data_rw 4096 2024-05-01 09:00 Download",
        "-rw-rw---- 1 u0_a1 ext_data_rw  123 2024-05-01 09:01 notes.txt",
        "-rw-rw---- 1 u0_a1 ext_data_rw  456 2024-05-01 09:02 my file.txt",
        "lrwxrwxrwx 1 root  root          10 2024-05-01 09:03 sdcard -> /storage",
    ])
    entries = files._parse_ls("/sdcard", output)
    assert [entry["name"] for entry in entries] == ["Download", "my file.txt", "notes.txt", "sdcard"]
    assert entries[0]["type"] == "dir"
    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["notes.txt"]["size"] == 123
    assert by_name["sdcard"]["type"] == "link"


def _client(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    client.__enter__()
    client.post("/api/setup", json={"password": PASSWORD})
    return client


def test_files_routes_require_online_device(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "live_serial", lambda store, alias, connected=None: None)
    client = _client(tmp_path)
    try:
        assert client.get("/api/devices/phone/files").status_code == 409
        assert client.get("/api/devices/phone/files/download?path=/x").status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_files_list_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "live_serial", lambda store, alias, connected=None: "SERIAL")
    monkeypatch.setattr(files, "list_dir", lambda serial, path: ([{"name": "a.txt", "path": "/sdcard/a.txt",
                                                                   "type": "file", "size": 1, "modified": "",
                                                                   "mode": "-rw", "owner": "u", "group": "u"}], ""))
    monkeypatch.setattr(files, "download", lambda serial, path: b"hello")

    client = _client(tmp_path)
    try:
        listing = client.get("/api/devices/phone/files?path=/sdcard/Download").json()
        assert listing["path"] == "/sdcard/Download"
        assert listing["parent"] == "/sdcard"
        assert listing["entries"][0]["name"] == "a.txt"

        downloaded = client.get("/api/devices/phone/files/download?path=/sdcard/a.txt")
        assert downloaded.status_code == 200
        assert downloaded.content == b"hello"
        assert "a.txt" in downloaded.headers["content-disposition"]
    finally:
        client.__exit__(None, None, None)
