# 🚀 Fenox Mobile

**One command to connect, monitor, and launch your Flutter apps on every device you own.**

Fenox bundles ADB connections, reverse-port binding, log streaming, screen mirroring, media capture, and Flutter launches into instant terminal aliases — USB, wireless, and emulator alike, including from WSL.

![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Python](https://img.shields.io/badge/python-3.8%2B-green) ![License](https://img.shields.io/badge/license-MIT-orange) ![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20WSL%20%7C%20macOS-lightgrey)

## ✨ Highlights

- 🔌 **USB + wireless + emulator** — auto-detected by `fenox doctor`; works from WSL via a shared Windows adb server
- ⚡ **Instant aliases** — `<app>-<device>` launches your app with ports bound and backend URLs set; aliases auto-reload when config changes
- 🔥 **Blast deploys** — `fenox run <app> @group` launches on every device in a group, side-by-side in tmux
- 👀 **Live watcher** — `fenox watch` re-binds reverse ports the moment a device (re)connects
- 📦 **Profiles** — `fenox profile export` on one machine, `import` on another; full setup in seconds
- 🧩 **Plugins** — drop a script in `~/.fenox/plugins/` and it becomes a `fenox <name>` command
- 🩺 **Doctor & crash triage** — parallel device health checks, one-command crash log extraction
- 🪟 **Clean UX** — bash + zsh completions, shell aliases, no tracebacks on Ctrl+C

## 📦 Install

**One-liner (prebuilt binary, no toolchain needed):**

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.sh | bash
```

**From source:**

```bash
git clone https://github.com/onefennox/fenox-mobile.git
cd fenox-mobile && bash install.sh
```

Both paths install to `~/.local/bin/fenox-mobile` with a `fenox` alias, and back up any previous install. Force a source build with `FENOX_BUILD_FROM_SOURCE=1 bash install.sh`.

## 🚀 Quick Start (60 seconds)

```bash
fenox init          # first-run setup: checks tools, installs the alias engine
fenox connect       # connects every saved device + binds all app ports
fenox doctor        # health-check; auto-adds any USB phone it finds
<app>-<device>      # e.g. myapp-myphone — your app launches on the device
```

### First time on a new phone?

1. Enable **Developer options → USB debugging** (or Wireless debugging), plug in
2. Accept the *"Allow USB debugging?"* RSA prompt on the phone (one time only)
3. `fenox doctor` auto-adds it → `fenox rename <generated-name> myphone` → done

## ⬆️ Updating

```bash
fenox update        # checks GitHub Releases, downloads + checksum-verifies, swaps atomically
```

Runs from a local repo clone? It rebuilds from source instead. Every release ships checksumed binaries for **linux-x86_64** and **linux-aarch64**.

## 🔌 USB Debugging (WSL)

WSL can't see USB devices directly, so Fenox routes **all** adb traffic to the Windows `adb.exe` server on port **5038**, while the Linux adb server stays on the default 5037 — that way a stray `adb` call can't start a competing server that hides your phone. `fenox doctor` reports which server it found (e.g. *port 5038 (shared Windows server)*).

1. Install **Android Platform Tools** on Windows so `adb.exe` exists.
2. Plug the phone into Windows and accept the *"Allow USB debugging?"* RSA prompt.
3. Run `fenox doctor` — it probes the Windows server and picks up every USB device.

Fenox looks for `adb.exe` in `C:\platform-tools`, your Windows `Android\Sdk\platform-tools`, and finally `where adb` on the Windows `PATH`. Wireless debugging needs none of this — use `fenox pair`.

## ⚙️ Configuration (`~/.fenox.json`)

All of your projects, remote server URLs, and test devices are managed in a single JSON file located at `~/.fenox.json`. This file is generated automatically the first time the program runs.

If you add a new device or start a new project, **simply edit this file**. Fenox Mobile will instantly read it and generate the required terminal commands dynamically! *(Note: If a device drops offline and you enter a custom IP/Port via the interactive prompt, the tool will offer to save it here automatically).*

### Example `~/.fenox.json`

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

> 🎯 `settings.remote_domain` is the convention used to guess remote API URLs (`https://<app>.<domain>/api`) when registering a new project — change it once and every future project follows it.

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
| Path | Flutter project (has `pubspec.yaml` + `android/`) found under `~/Projects` |
| Alias | Repo name for generic dirs (`mobile`, `app`, `frontend`…), else the folder name |
| Backend port | Sniffed from `.env` (`PORT=`), `package.json` scripts, or Python servers |
| `api_local` | `http://localhost:<port>/api` |
| `api_remote` | `https://<app>.<remote_domain>/api` (edit `settings.remote_domain` once) |
| Backend launcher | `npm run dev` / `npm start` / `python <file>` / `go run .` |
| Android package | Resolved from `build.gradle` / `AndroidManifest.xml` |

Aliases for the new app (`<app>-all`, `<app>-release`, `<app>-<device>`…) are **live immediately** — the shell watches `~/.fenox.json` and reloads them for you.

## 🖥️ Interactive Dashboard

Running `fenox-mobile` with no arguments opens a **live dashboard**: device telemetry (battery 🔋, screen, Android version, storage, foreground app, health score), app status (git branch, auto-resolved package name, last run), and per-device / per-app quick actions (mirror, screenshot, record, logs, wake/lock, bind, nuke, build, run). Press `x` to exit.

## 💾 Where Files Land (Windows Desktop)

Everything auto-saves under `C:\Users\<you>\Desktop\Fenox\` so it's viewable from Windows:

| Output | Location |
| --- | --- |
| 📸 Screenshots | `Desktop\Fenox\Screenshots\<device>\` (also copied to clipboard) |
| 🎥 Recordings | `Desktop\Fenox\Recordings\<device>\` |
| 📋 Logs | `Desktop\Fenox\Logs\<app>_<device>_<ts>.log` (crash lines flagged) |
| 📦 Release APKs | `Desktop\Fenox\APKs\<app>_release_<ts>.apk` |

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