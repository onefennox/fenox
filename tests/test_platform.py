import os
import stat
from pathlib import Path

from fenox.core import doctor, host


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_detect_os_is_one_of_the_known_values():
    assert host.HOST.os in ("linux", "wsl", "macos", "windows")
    assert host.IS_LINUX == (host.HOST.os == "linux")
    assert host.IS_WSL == (host.HOST.os == "wsl")


def test_adb_candidates_include_the_android_sdk_root(monkeypatch):
    monkeypatch.setenv("ANDROID_HOME", "/opt/custom-sdk")
    candidates = host.adb_candidates()
    assert "/opt/custom-sdk/platform-tools/adb" in candidates


def test_adb_client_honours_a_configured_path(tmp_path, monkeypatch):
    binary = _executable(tmp_path / "custom" / "adb")
    # A stale Android home must not win over an explicit path.
    monkeypatch.setenv("ANDROID_HOME", "/nonexistent")
    assert host.adb_client(str(binary)) == str(binary)


def test_flutter_candidates_include_flutter_root_and_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUTTER_ROOT", "/opt/flutter-root")
    candidates = host.flutter_candidates()
    assert "/opt/flutter-root/bin/flutter" in candidates

    configured = tmp_path / "sdk"
    (configured / "bin").mkdir(parents=True)
    assert str(configured / "bin" / "flutter") in host.flutter_candidates(str(configured))


def test_find_flutter_prefers_a_project_fvm_sdk(tmp_path):
    project = tmp_path / "app"
    sdk = _executable(project / ".fvm" / "flutter_sdk" / "bin" / "flutter")
    found = host.find_flutter(project=str(project))
    assert found == str(sdk)


def test_find_flutter_accepts_the_binary_or_its_directory(tmp_path):
    binary = _executable(tmp_path / "flutter" / "bin" / "flutter")
    assert host.find_flutter(str(binary)) == str(binary)
    assert host.find_flutter(str(tmp_path / "flutter")) == str(binary)


def test_doctor_tools_reports_resolution(tmp_path, monkeypatch):
    binary = _executable(tmp_path / "sdk" / "bin" / "flutter")
    monkeypatch.setenv("FLUTTER_ROOT", str(tmp_path / "sdk"))
    report = doctor.tools({})
    assert report["os"] == host.HOST.os
    assert "adb" in report and "client" in report["adb"]
    assert report["flutter"]["path"] == str(binary)
    assert "scrcpy" in report


def test_session_flutter_resolution_is_unaffected_by_an_empty_setting(tmp_path, monkeypatch):
    # An empty flutter_path means "detect", not "no Flutter".
    binary = _executable(tmp_path / "flutter" / "bin" / "flutter")
    monkeypatch.setenv("PATH", f"{binary.parent}:{os.environ['PATH']}")
    assert host.find_flutter("") == str(binary)
