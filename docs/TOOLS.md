# Tool detection

Fenox finds the tools it needs (adb, Flutter, scrcpy) automatically. Detection is
centralised in `core/host.py`; `fenox doctor` prints exactly what was resolved and
`fenox config` lets the owner override any path.

## Platform

`host.detect_os()` returns one of `linux`, `wsl`, `macos`, `windows`
(`/proc/version` contains `microsoft`, or `WSL_DISTRO_NAME` is set, means WSL).
The supported targets today are **Linux and WSL**.

## adb

On WSL, USB is only visible to Windows, so Fenox keeps two roles:

| Role | What it is |
| --- | --- |
| **server** | starts and owns the shared adb server; on WSL this is Windows `adb.exe` |
| **client** | runs the queries; a Linux adb can talk to the Windows server over the shared port |

Resolution order for the **client**:

1. `settings.adb_path`, or `FENOX_ADB_PATH`
2. `adb` on `PATH`
3. `$ANDROID_HOME/platform-tools/adb`, `$ANDROID_SDK_ROOT/platform-tools/adb`
4. `~/Android/Sdk/platform-tools/adb` (Linux), `~/Library/Android/sdk/platform-tools/adb` (macOS)
5. `/usr/lib/android-sdk`, `/opt/android-sdk`, `~/platform-tools/adb`
6. `/snap/bin/adb`, `/home/linuxbrew/.linuxbrew/bin/adb`
7. Windows adb on WSL: `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`
   (`/mnt/c/Users/<user>/AppData/Local/Android/Sdk/platform-tools/adb.exe`)

## Flutter

Resolution order, checked per project so each project can use its own SDK:

1. The project's FVM SDK: `.fvm/flutter_sdk/bin/flutter`, `.fvm/flutter/bin/flutter`,
   or the version named in `.fvmrc` under `~/fvm/versions/<version>/bin/flutter`
2. `settings.flutter_path` (accepts the SDK directory or the binary)
3. `$FLUTTER_ROOT/bin/flutter`
4. `flutter` on `PATH`
5. Common installs: `~/flutter`, `~/development/flutter`, `~/.flutter-sdk/flutter`,
   `~/.local/share/flutter`, `~/fvm/default`, `~/.fvm/default`, `~/.asdf/shims/flutter`
6. Snap and Homebrew: `/snap/bin/flutter`, `/home/linuxbrew/.linuxbrew/bin/flutter`

## scrcpy

The server jar is found the way scrcpy itself finds it:

1. `$SCRCPY_SERVER_PATH`
2. `<prefix>/share/scrcpy/scrcpy-server` for the resolved `scrcpy` binary
   (`/usr/share/scrcpy/scrcpy-server` on Debian/Ubuntu, `/usr/local/share/...` for a source build)
3. Next to the binary, for portable builds
4. `/snap/scrcpy/current/usr/local/share/scrcpy/scrcpy-server`

## Overrides

```bash
fenox doctor                                  # what was detected, and why
fenox config set flutter_path ~/flutter       # or the binary path
fenox config set adb_path /usr/bin/adb
fenox config list
```

The same values are editable in the web app under **Settings → Tools**, which
also shows the resolved adb client/server, Flutter, and scrcpy with their
versions.

## Installation

`packaging/install.sh` reports whether it is running on Linux or WSL, runs
`fenox doctor`, and — when Flutter is not found — offers to record its location
straight away.
