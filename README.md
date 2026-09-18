# 🚀 Fenox Mobile

**One command to connect, monitor, and launch your Flutter apps on every device you own.**

Fenox bundles ADB connections, reverse-port binding, log streaming, screen mirroring, media capture, and Flutter launches into instant terminal aliases — USB, wireless, and emulator alike, including from WSL.

![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Python](https://img.shields.io/badge/python-3.8%2B-green) ![License](https://img.shields.io/badge/license-MIT-orange) ![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20WSL%20%7C%20Windows-lightgrey)

## ✨ Highlights

- 🔌 **USB + wireless + emulator** — auto-detected by `fenox doctor`; works from WSL via a shared Windows adb server
- ⚡ **Instant aliases** — `<app>-<device>` launches your app with ports bound and backend URLs set; aliases auto-reload when config changes
- 🔥 **Blast deploys** — `fenox run <app> @group` launches on every device in a group, side-by-side in tmux
- 👀 **Live watcher** — `fenox watch` re-binds reverse ports the moment a device (re)connects
- 📦 **Profiles** — `fenox profile export` on one machine, `import` on another; full setup in seconds
- 🧩 **Plugins** — drop a script in `~/.fenox/plugins/` and it becomes a `fenox <name>` command
- 🩺 **Doctor & crash triage** — parallel device health checks, one-command crash log extraction
- 🪟 **Clean UX** — bash + zsh completions, shell aliases, no tracebacks on Ctrl+C

## 📋 Requirements

| | Needed for |
| --- | --- |
| **Linux** (x86_64 or aarch64) or **WSL** | the bash installer and the prebuilt binaries |
| **Windows** 10/11 | the PowerShell installer and the prebuilt `.exe` |
| `adb` | everything — from Android platform-tools |
| `flutter` | launching and building your apps |
| `scrcpy` | screen mirroring — optional |
| `tmux` | `fenox run <app> all` blast deploys — Linux/WSL only, optional |
| `python3` 3.8+ | only for a from-source build or plugins |

macOS is **not** supported: there is no macOS build, and the Linux binaries
cannot run there. The installer tells you so instead of installing something
that will not start.

## 📦 Install

**Linux / WSL** — prebuilt binary, no toolchain needed:

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.sh | bash
```

**Windows** — from PowerShell:

```powershell
irm https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.ps1 | iex
```

The Windows installer puts `fenox-mobile.exe` in
`%LOCALAPPDATA%\Programs\fenox`, adds it to your user `PATH`, and back that
previous install up. Use `install.ps1 -Version v1.0.0` to pin a release, or
`-NoPath` to leave `PATH` alone.

**From source** (Linux/WSL):

```bash
git clone https://github.com/onefennox/fenox-mobile.git
cd fenox-mobile && bash install.sh
```

The bash installer installs to `~/.local/bin/fenox-mobile` with a `fenox` alias
and backs up any previous install. Force a source build with
`FENOX_BUILD_FROM_SOURCE=1 bash install.sh`.

Every path downloads from GitHub Releases and **verifies the SHA-256 before
installing anything** — if no checksum is published, or it does not match,
nothing is written.

## 🚀 Quick Start (60 seconds)

```bash
fenox init          # one-time setup — see below
fenox connect       # connects every saved device + binds all app ports
fenox doctor        # health-check; auto-adds any USB phone it finds
<app>-<device>      # e.g. myapp-myphone — your app launches on the device
```

### What `fenox init` asks you (once)

1. **Where do your Flutter projects live?** It validates the path and offers to
   create it, then remembers it in `~/.fenox.json`. Nothing else ever has to
   guess. Re-run the questions any time with `fenox init --reset-settings`.
2. **Your remote API domain** (optional) — used to guess production URLs as
   `https://<app>.<domain>/api`. Press Enter to skip; fenox asks later only if a
   remote launch or release build actually needs it.

It then offers to install the alias engine and shell completions into your
`~/.bashrc` or `~/.zshrc`, and to scan your projects directory right away.

Runs without a terminal (CI, scripts)? It skips the questions instead of
hanging, and falls back to your projects directory only until you run it for
real.

### First time on a new phone?

1. Enable **Developer options → USB debugging** (or Wireless debugging), plug in
2. Accept the *"Allow USB debugging?"* RSA prompt on the phone (one time only)
3. `fenox doctor` auto-adds it → `fenox rename <generated-name> myphone` → done

## ⬆️ Updating

```bash
fenox update        # checks GitHub Releases, downloads + checksum-verifies, swaps atomically
```

Runs from a local repo clone? It rebuilds from source instead. Every release ships checksum-verified binaries for **linux-x86_64**, **linux-aarch64** and **windows-x86_64**, each with a `.sha256` file and an aggregate `SHA256SUMS`.

## 🔌 USB Debugging (WSL)

WSL can't see USB devices directly, so Fenox routes **all** adb traffic to the Windows `adb.exe` server on port **5038**, while the Linux adb server stays on the default 5037 — that way a stray `adb` call can't start a competing server that hides your phone. `fenox doctor` reports which server it found (e.g. *port 5038 (shared Windows server)*).

1. Install **Android Platform Tools** on Windows so `adb.exe` exists.
2. Plug the phone into Windows and accept the *"Allow USB debugging?"* RSA prompt.
3. Run `fenox doctor` — it probes the Windows server and picks up every USB device.

Fenox looks for `adb.exe` in `C:\platform-tools`, your Windows `Android\Sdk\platform-tools`, and finally `where adb` on the Windows `PATH`. Wireless debugging needs none of this — use `fenox pair`.

## ⚙️ Configuration (`~/.fenox.json`)

All of your projects, remote server URLs, and test devices are managed in a single JSON file located at `~/.fenox.json`.

It starts **empty** and fills up from what you actually do: `fenox init` records your projects directory and remote domain, `fenox doctor` and `fenox discover` add devices, and `fenox scan`/`add-app` add projects. You can also edit it by hand at any time — Fenox reads it immediately and regenerates the terminal commands, live.

> 🎯 A `settings.remote_domain` of `""` simply means "not configured yet". Set it once in `fenox init` and every project registered afterwards follows the convention (`https://<app>.<domain>/api`).

### Example `~/.fenox.json`

Here is what it looks like once you have registered one project and one device
(the names are yours, not defaults — nothing is pre-filled):

```
{
    "apps": {
        "myapp": {
            "path": "~/Projects/MyApp/apps/mobile",
            "port": "4000",
            "api_local": "http://localhost:4000",
            "api_remote": "https://myapp.example.com",
            "backend": {
                "path": "~/Projects/MyApp/apps/server",
                "cmd": "npm run dev"
            }
        }
    },
    "devices": {
        "mydevice": {
            "ip": "192.168.0.248",
            "port": "5555",
            "model": "Pixel 8"
        }
    },
    "settings": {
        "remote_domain": "example.com",
        "projects_dir": "~/Projects"
    }
}
```

> 💡 If a device drops offline and you supply a custom IP/port at the prompt, fenox offers to save it here for next time.

## ⚡ Command Reference Table

The system dynamically reads your `~/.fenox.json` file and creates instant 1-word commands.

The examples below use **`myapp`** (as the app) and **`mydevice`** (as the device) based on the default configuration. You can substitute these with any app or device you have added to your config (e.g., `myapp-mydevice`).

### The "Auto-Alias" Commands

| Command | Category | Action & Description |
| --- | --- | --- |
| `myapp-mydevice` | 🚀 **Launch** | Wakes device, binds local ports, and launches Flutter (Local API). Prompts for IP/Port if device is offline. |
| `myapp-mydevice-remote` | 🚀 **Launch** | Binds ports and launches Flutter pointing to the **remote** production backend. |
| `myapp-release` | 🚀 **Launch** | Navigates to the project directory and builds a release APK. |
| `myapp-all` | 🔥 **Blast Deploy** | Opens `tmux`, splits screen side-by-side, connects to **all** online devices (asks which offline ones to try), and runs Flutter simultaneously. |
| `myapp-mydevice-nuke` | ☢️ **Nuke Protocol** | **1-second factory reset:** Runs `flutter clean`, `pub get`, uninstalls the app package from the phone via ADB, and reinstall. |
| `mydevice-screenshot` | 📸 **Media Capture** | Takes a UI screenshot, pulls it to your Windows Pictures folder, and **instantly copies it to your clipboard**. |
| `mydevice-record` | 📸 **Media Capture** | Starts screen recording. Press `Enter` to stop, and it pulls the `.mp4` directly to your Windows folder. |
| `mydevice-mirror` | 📱 **Screen & Logs** | Uses `scrcpy` to instantly open a native window mirroring the phone's screen over Wi-Fi. |
| `myapp-mydevice-logs` | 📱 **Screen & Logs** | Hunts down the app's PID and streams **only** the logs for that exact Flutter process (ignores system noise). |
| `myapp-mydevice-bind` | 🔗 **Connections** | Instantly re-establishes the reverse TCP port connection between the physical phone and your local backend. |
| `fenox-bind-all` | 🔗 **Connections** | Loops through every connected device and maps all configured app ports globally. |
| `fenox-doctor` | 🩺 **System Health** | **The Panic Button:** Kills ADB, restarts it, silently reconnects saved ports, shows a health table, then **asks which offline device to fix (or `all`/`skip`)** — port prompts only for what you pick. Binds all ports. |
| `fenox-sync` | 🔄 **Sync** | Reconnects devices on saved ports silently (mDNS first), then asks **which offline device to fix (or `all`/`skip`)**. |
| `fenox-discover` | 📡 **Discovery** | Finds new wireless-debugging devices via mDNS (optional nmap subnet scan) and adds them to config with one key. |
| `fenox-shot-all` | 📸 **Batch Capture** | Screenshots every connected device into `Desktop\Fenox\Screenshots\<device>\`. |
| `fenox-add-app` | ➕ **Add App** | Registers a project — **zero prompts** when given flags (`--name`, `--path`, `--port`, `--api-local`, `--api-remote`, `--backend-path`, `--backend-cmd`, `--yes`), guided wizard otherwise. `--update` re-registers an existing app. |
| `fenox-scan` | 🔎 **Scan Projects** | **Zero-friction:** finds every Flutter project under `~/Projects`, auto-detects backend port & launcher, guesses API URLs, and registers everything — no prompts. `--dry-run` to preview. |
| `<app>-backend` | 🖥️ **Backend** | Starts the app's backend (`npm run dev` etc.) in a tmux session. |
| `<app>-hot` | ⚡ **Hot Reload** | Sends `r` to the running Flutter session (add `--full` for hot restart). |
| `<app>-install` | 📦 **Install** | Installs the latest release APK to every connected device. |
| `fenox-mobile open <app> <device>` | 🚀 **Open App** | Launches the app on a device via `am start`. |
| `fenox-pair` | 📶 **Setup** | Triggers the Android 11+ Wireless Pairing Wizard. Pairs new devices over Wi-Fi using the 6-digit code (no USB). |

## ➕ Zero-Friction Onboarding (new project in one step)

Everything lives in `~/Projects` — so let the tool do the work:

```bash
# 1. Register EVERY new Flutter project in ~/Projects automatically:
fenox-mobile scan                # detects path, backend port, API URLs, backend launcher — no prompts
fenox-mobile scan --dry-run      # preview first, writes nothing

# 2. Or register a single project by name (auto-located, zero prompts):
fenox-mobile add-app --name topmonie --yes

# 3. Fix a wrong guess (e.g. custom API domain) without re-typing everything:
fenox-mobile add-app --name topmonie --api-remote https://api.topmonie.com --update --yes
```

What gets auto-detected:

| Field | How it's guessed |
| --- | --- |
| Path | Flutter project (has `pubspec.yaml` + `android/`) found under your projects directory |
| Alias | Repo name for generic dirs (`mobile`, `app`, `frontend`…), else the folder name |
| Backend port | Sniffed from `.env` (`PORT=`), `package.json` scripts, or Python servers |
| `api_local` | `http://localhost:<port>/api` |
| `api_remote` | `https://<app>.<remote_domain>/api` (from your one-time setup in `fenox init`) |
| Backend launcher | `npm run dev` / `npm start` / `python <file>` / `go run .` |
| Android package | Resolved from `build.gradle` / `AndroidManifest.xml` |

Aliases for the new app (`<app>-all`, `<app>-release`, `<app>-<device>`…) are **live immediately** — the shell watches `~/.fenox.json` and reloads them for you.

## 🖥️ Interactive Dashboard

Running `fenox-mobile` with no arguments opens a **live dashboard**: device telemetry (battery 🔋, screen, Android version, storage, foreground app, health score), app status (git branch, auto-resolved package name, last run), and per-device / per-app quick actions (mirror, screenshot, record, logs, wake/lock, bind, nuke, build, run). Press `x` to exit.

## 💾 Where Files Land

On WSL everything saves under `C:\Users\<you>\Desktop\Fenox\`, so it is viewable
from Windows. Everywhere else the same layout lives under `~/Fenox`: on Linux
that is `~/Fenox`, and on Windows `%USERPROFILE%\Desktop\Fenox`.

| Output | Location |
| --- | --- |
| 📸 Screenshots | `Fenox/Screenshots/<device>/` (also copied to clipboard) |
| 🎥 Recordings | `Fenox/Recordings/<device>/` |
| 📋 Logs | `Fenox/Logs/<app>_<device>_<ts>.log` (crash lines flagged) |
| 📦 Release APKs | `Fenox/APKs/<app>_release_<ts>.apk` |

## 🛠️ Raw CLI Commands (Advanced/Scripting)

If you prefer using the tool explicitly or want to script it further, you can use the raw CLI arguments:

| Command | Description |
| --- | --- |
| `fenox-mobile` | Opens the interactive GUI menu. |
| `fenox-connect` | ⚡ **One-shot connect**: connects all devices (USB + wireless, no prompts), explains stuck devices, binds all ports. `fenox-connect <device>` for one. |
| `fenox-mobile rename <old> <new>` | ✏️ **Rename device** — regenerates all aliases instantly. `m` in the menu does the same. |
| `fenox-mobile run myapp mydevice` | Standard launch. Use `all` as the device for Tmux blast deployment (`fenox-mobile run myapp all`). |
| `fenox-mobile run myapp mydevice --remote` | Launch targeting remote backend. |
| `fenox-mobile bind myapp mydevice` | Bind ports for a specific app/device. |
| `fenox-mobile build myapp` | Build release APK. |
| `fenox-mobile logs myapp mydevice` | Stream app-specific logs. |
| `fenox-mobile mirror mydevice` | Start Scrcpy mirroring. |
| `fenox-mobile pair` | Start Wireless Pairing Wizard. |
| `fenox-mobile doctor` | Run full system health check and restart. |
| `fenox-mobile init` | One-time setup. `--reset-settings` re-asks the questions. |
| `fenox-mobile uninstall` | Remove fenox, its config and its shell hooks. `--yes` skips the prompt, `--keep-config` keeps `~/.fenox.json`. |

## 🧹 Uninstall

```bash
fenox uninstall              # shows exactly what it will remove, then confirms
fenox uninstall --yes        # no prompt (for scripting)
fenox uninstall --keep-config  # keep ~/.fenox.json and your devices/apps
```

It removes the installed binary, the `fenox` symlink, the config, config backups
and the run history, and strips only its own hooks from `~/.bashrc` and
`~/.zshrc` — other lines in those files are left untouched. On Windows, run
`fenox-mobile uninstall` and then remove `%LOCALAPPDATA%\Programs\fenox` from
your `PATH`. Running it from a source checkout never deletes the checkout.

## 🩺 Troubleshooting

**`fenox doctor` finds no devices.** Make sure `adb` is on your `PATH`, the
phone is unlocked, and you have accepted the *"Allow USB debugging?"* prompt on
the device. On WSL, USB only works through the Windows adb server — see below.

**`<app>-<device>` alias not found.** Aliases live in your shell, so re-source
your rc file (`source ~/.bashrc`) or open a new terminal. Check the hook is
installed: `fenox init` prints whether it is.

**"command not found: fenox".** `~/.local/bin` is not on your `PATH`. Add
`export PATH="$HOME/.local/bin:$PATH"` to your rc file, or re-run the installer.

**Checksum mismatch on install.** The download did not match the published
SHA-256, so nothing was installed. This is almost always a stale mirror or a
flaky connection — retry, or install from a clone with
`FENOX_BUILD_FROM_SOURCE=1 bash install.sh`.

**Config got corrupted.** Fenox backs the file up to `~/.fenox.json.corrupt-<ts>`
and starts from a clean one rather than failing. Rolling backups of the last five
versions are kept in `~/.fenox-backups/`.

**`fenox build` refuses to run.** A release APK needs a remote API URL. Set your
domain once with `fenox init`, or per app with
`fenox add-app --api-remote https://api.example.com --update --yes`.

## ❓ FAQ

**Does it work on macOS?** No. Fenox ships Linux and Windows builds only; the
README used to claim macOS, and the installer now refuses clearly rather than
installing a Linux binary that cannot run.

**Does it need a Python toolchain?** No. The installers fetch a self-contained
binary. Python 3.8+ is only needed to build from source or to write plugins.

**Where is my data?** Everything is local: `~/.fenox.json` (devices, apps,
groups), `~/.fenox/` (plugins, profiles, hooks), `~/.fenox-backups/`. Use
`fenox profile export <name>` to move a setup between machines.

**How do I pin a version?** Built from a clone, edit `VERSION`. On Windows,
`install.ps1 -Version v1.0.0`. On Linux, install from a clone at that tag.

**A device went offline and came back.** `fenox watch` re-binds reverse ports as
soon as a device reconnects, and `fenox sync` reconnects known devices on demand.

## 🤝 Contributing

Bug reports, fixes and documentation are all welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions and how releases are
cut, and [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

Please report security problems privately via
[SECURITY.md](SECURITY.md), and note that this project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md).