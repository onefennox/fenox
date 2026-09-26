import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from fenox.core import doctor, host

# These build a `#!/bin/sh` file and mark it executable, which is a POSIX idea.
# The resolution logic they cover is worth testing on macOS and Linux, where the
# path shapes match, and is exercised on Windows by the recorded fixtures in
# test_connect.py instead.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX executables")


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


@posix_only
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


@posix_only
def test_find_flutter_prefers_a_project_fvm_sdk(tmp_path):
    project = tmp_path / "app"
    sdk = _executable(project / ".fvm" / "flutter_sdk" / "bin" / "flutter")
    found = host.find_flutter(project=str(project))
    assert found == str(sdk)


@posix_only
def test_find_flutter_accepts_the_binary_or_its_directory(tmp_path):
    binary = _executable(tmp_path / "flutter" / "bin" / "flutter")
    assert host.find_flutter(str(binary)) == str(binary)
    assert host.find_flutter(str(tmp_path / "flutter")) == str(binary)


@posix_only
def test_doctor_tools_reports_resolution(tmp_path, monkeypatch):
    binary = _executable(tmp_path / "sdk" / "bin" / "flutter")
    monkeypatch.setenv("FLUTTER_ROOT", str(tmp_path / "sdk"))
    report = doctor.tools({})
    assert report["os"] == host.HOST.os
    assert "adb" in report and "client" in report["adb"]
    assert report["flutter"]["path"] == str(binary)
    assert "scrcpy" in report


@posix_only
def test_session_flutter_resolution_is_unaffected_by_an_empty_setting(tmp_path, monkeypatch):
    # An empty flutter_path means "detect", not "no Flutter".
    binary = _executable(tmp_path / "flutter" / "bin" / "flutter")
    monkeypatch.setenv("PATH", f"{binary.parent}:{os.environ['PATH']}")
    assert host.find_flutter("") == str(binary)


# --- host coverage ----------------------------------------------------------
# The point of these is that a candidate list built on one platform stays useful
# on another. Fenox probes the same list everywhere, so every name has to be
# tried in both forms rather than only the one the author happened to use.

def test_adb_candidates_include_both_executable_names(monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(host, "WINDOWS_ADB", None)
    monkeypatch.setattr(host, "HOST", host.Host("linux"))

    candidates = host.adb_candidates()

    assert any(path.endswith("adb.exe") for path in candidates)
    assert any(path.endswith(os.sep + "adb") for path in candidates)


def test_adb_candidates_include_windows_sdk_locations(monkeypatch):
    monkeypatch.setattr(host, "HOST", host.Host("linux"))
    monkeypatch.setattr(host, "WINDOWS_ADB", None)
    monkeypatch.setenv("LOCALAPPDATA", "/tmp/fake-localappdata")

    candidates = host.adb_candidates()

    assert any("Android" in path and "Sdk" in path for path in candidates)


def test_adb_candidates_include_homebrew_prefixes(monkeypatch):
    """A Mac with only `brew install android-platform-tools` used to look bare."""
    monkeypatch.setattr(host, "HOST", host.Host("macos"))
    monkeypatch.setattr(host, "WINDOWS_ADB", None)

    candidates = host.adb_candidates()

    assert any(path.startswith("/opt/homebrew/") for path in candidates)
    assert any(path.startswith("/usr/local/") for path in candidates)


def test_flutter_candidates_include_the_windows_launcher(monkeypatch):
    """Windows ships flutter.bat, so a list mentioning only `flutter` finds nothing."""
    monkeypatch.setattr(host, "HOST", host.Host("windows"))
    monkeypatch.delenv("FLUTTER_ROOT", raising=False)

    candidates = host.flutter_candidates()

    assert any(path.endswith("flutter.bat") for path in candidates)
    assert any(path.endswith(os.sep + "flutter") for path in candidates)


def test_flutter_candidates_still_resolve_a_posix_sdk(tmp_path, monkeypatch):
    """A POSIX SDK root still resolves.

    Deliberately built under tmp_path rather than the real home: the autouse
    `isolated_home` fixture redirects HOME, but a test that would overwrite a
    real SDK launcher if that fixture ever changed should not depend on it to
    stay safe.
    """
    monkeypatch.setattr(host, "HOST", host.Host("linux"))
    monkeypatch.delenv("FLUTTER_ROOT", raising=False)
    # Empty PATH so `which` cannot find a real SDK and assert against that.
    monkeypatch.setenv("PATH", "")
    sdk = tmp_path / "flutter"
    binary = _executable(sdk / "bin" / "flutter")

    assert str(binary) in host.flutter_candidates(str(sdk))
    # And the plain `flutter` name is still probed, not only the suffixed one.
    assert any(path.endswith(os.sep + "flutter") for path in host.flutter_candidates())


# --- shell completions -----------------------------------------------------
# The user's .zshrc sources this on every new terminal, so it has to stay fast,
# silent and in step with the parser.

def test_completions_list_every_subcommand():
    from fenox.cli.main import build_parser

    parser = build_parser()
    group_actions = getattr(parser._subparsers, "_group_actions", [])  # noqa: SLF001
    expected = sorted(
        choice
        for action in group_actions
        if isinstance(action.choices, dict)
        for choice in action.choices
    )

    for shell in ("bash", "zsh"):
        script = capsys_output(shell)
        for command in expected:
            assert command in script, f"{command} missing from the {shell} completion"


def capsys_output(shell: str) -> str:
    import io
    from contextlib import redirect_stdout

    from fenox.cli.main import main

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        assert main(["--generate-completions", shell]) == 0
    return buffer.getvalue()


def test_completions_are_valid_shell_syntax():
    """A completion that does not parse breaks the shell that sources it."""
    import subprocess


    for shell, flag in (("bash", "-n"), ("zsh", "-n")):
        binary = shutil.which(shell)
        if not binary:
            continue  # not installed on this machine; the other one still checks
        script = capsys_output(shell)
        result = subprocess.run([binary, flag], input=script, capture_output=True, text=True)
        assert result.returncode == 0, f"{shell} rejected the completion: {result.stderr}"
