# 🚀 Fenox

**One command to connect, monitor, and launch your Flutter apps on every device you own.**

Fenox bundles ADB connections, reverse-port binding, log streaming, screen mirroring, media capture, and Flutter launches into instant terminal aliases — USB, wireless, and emulator alike, including from WSL.

![Version](https://img.shields.io/badge/version-1.0.1-blue) ![Python](https://img.shields.io/badge/python-3.8%2B-green) ![License](https://img.shields.io/badge/license-MIT-orange) ![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20WSL-lightgrey)

## ✨ Highlights

- 🔌 **USB + wireless + emulator** — auto-detected by `fenox doctor`; works from WSL via a shared Windows adb server
- ⚡ **Instant aliases** — `<app>-<device>` launches your app with ports bound and backend URLs set; aliases auto-reload when config changes
- 📨 **Your phone's own data** — `fenox phone messages` reads texts, threads and unread counts straight from the phone: no root, nothing installed on it
- 🔥 **Blast deploys** — `fenox run <app> @group` launches on every device in a group, side-by-side in tmux
- 👀 **Live watcher** — `fenox watch` re-binds reverse ports the moment a device (re)connects
- 📦 **Profiles** — `fenox profile export` on one machine, `import` on another; full setup in seconds
- 🧩 **Plugins** — drop a script in `~/.fenox/plugins/` and it becomes a `fenox <name>` command
- 🩺 **Doctor & crash triage** — parallel device health checks, one-command crash log extraction
- 🪟 **Clean UX** — bash + zsh completions, shell aliases, no tracebacks on Ctrl+C

## 📋 Requirements

| | Needed for |
| --- | --- |
| **Linux** (x86_64 or aarch64) or **WSL** | the installer and the prebuilt binaries |
| `adb` | everything — from Android platform-tools |
| `flutter` | launching and building your apps |
| `scrcpy` | screen mirroring — optional |
| `tmux` | `fenox run <app> all` blast deploys — optional |
| `python3` 3.8+ | only for a from-source build or plugins |

**Platform support: Linux and WSL.** macOS and native Windows are not supported —
there is no build for either, and the Linux binaries cannot run there, so the
installer refuses with a clear message rather than installing something that
will not start. On a Windows machine you run fenox *inside* WSL; that is what
WSL support means here.

## 📦 Install

**Linux / WSL** — prebuilt binary, no toolchain needed:

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/install.sh | bash
```

**From source:**

```bash
git clone https://github.com/onefennox/fenox.git
cd fenox && bash install.sh
```

The bash installer installs to `~/.local/bin/fenox` with a `fenox` alias
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

Runs from a local repo clone? It rebuilds from source instead. Every release ships checksum-verified binaries for **linux-x86_64** and **linux-aarch64**, each with a `.sha256` file and an aggregate `SHA256SUMS`.

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
| `mydevice-screenshot` | 📸 **Media Capture** | Takes a UI screenshot, pulls it into your `Fenox/Screenshots/<device>/` folder, and **instantly copies it to your clipboard** (WSL: the Windows clipboard). |
| `mydevice-record` | 📸 **Media Capture** | Starts screen recording. Press `Enter` to stop, and it pulls the `.mp4` straight into `Fenox/Recordings/<device>/`. |
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
| `fenox open <app> <device>` | 🚀 **Open App** | Launches the app on a device via `am start`. |
| `fenox-pair` | 📶 **Setup** | Triggers the Android 11+ Wireless Pairing Wizard. Pairs new devices over Wi-Fi using the 6-digit code (no USB). |

## ➕ Zero-Friction Onboarding (new project in one step)

Everything lives in `~/Projects` — so let the tool do the work:

```bash
# 1. Register EVERY new Flutter project in ~/Projects automatically:
fenox scan                # detects path, backend port, API URLs, backend launcher — no prompts
fenox scan --dry-run      # preview first, writes nothing

# 2. Or register a single project by name (auto-located, zero prompts):
fenox add-app --name topmonie --yes

# 3. Fix a wrong guess (e.g. custom API domain) without re-typing everything:
fenox add-app --name topmonie --api-remote https://api.topmonie.com --update --yes
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

Running `fenox` with no arguments opens with a **session screen** — the
banner, then a checklist of your config file, the shared adb server (started
behind a spinner), your projects directory and the shell hooks — so it is obvious
what is ready and what is not before you touch anything.

From there you are in a **live dashboard** that keeps itself up to date while you
decide what to do:

- **One list, a number or two keys.** Devices, apps and maintenance tasks are
  rows in a single selection list under their own headings, on one shared column
  grid. Move with `↑`/`↓` and confirm with **Enter**, or just type the row's key:
  `1` opens device 1, `d` runs Doctor, no second keystroke needed. The screen
  refreshes itself every few seconds while you decide, and `Esc`/`b` step back.
  On terminals 100 columns or wider the devices and apps sit in one column with
  the maintenance actions beside them; narrower, everything stacks.
- **Device telemetry**: battery 🔋, screen, Android version, storage, foreground
  app and a health score, plus app status (git branch, resolved package name,
  last run).
- **The whole toolset for a device on one screen.** All ~45 actions — Screen &
  input, Apps, Files, Device control, Dev tools and Configure — are visible at
  once, grouped under those headings and numbered straight through, so nothing is
  buried behind a category menu. Type the number and press Enter, or arrow to it.
- **An input line at the bottom.** Keystrokes land there first, which is what
  makes multi-digit numbers possible (`12` would otherwise fire `1` on the way).
  It shows what you typed, turns red when it names nothing on the screen, and
  supports `Backspace` to edit and `Esc` to clear before it goes back.
- **Consistent screens**: every menu carries a breadcrumb, names the device or
  app it acts on, groups its actions, and uses `b`/`Esc` to go back. Nothing
  clears the screen, so the session and your scrollback stay where they were.
- **The cursor stays where you put it** when you go back to a menu, and the
  chosen row is highlighted rather than described.
- **Quiet navigation**: unknown keys are ignored instead of printing an error and
  demanding Enter, and `b` always goes back.

The opening screen also carries a **tip** that rotates daily and only ever
mentions things that apply to your setup.

**Leaving is just as tidy:** press `x` or `Esc`, or hit `Ctrl+C` — every exit path
prints a sign-off with the session duration, anything you deployed, and the
single most useful thing to do next. `Ctrl+C` exits `130` from anywhere, and no
exit path ever shows a traceback.

When stdin is not a terminal (piped input, CI), the screens still print and the
menu falls back to a validated line prompt, so scripts keep working.

## 📨 Your Phone's Data, From the Terminal

The adb `shell` user is granted `READ_SMS`, `READ_CALL_LOG`, `READ_CONTACTS` and
`READ_CALENDAR` on a stock device, so the phone's own data can be read with **no
root and nothing installed on the phone**:

```bash
fenox phone messages                  # threads, newest first, with unread counts
fenox phone messages --unread         # only what needs attention
fenox phone messages --thread 151     # one conversation, oldest first
fenox phone messages --search "invoice"
fenox phone messages --thread 151 --mark-read
fenox phone messages --json           # for your own scripts
fenox phone messages --redact         # hide numbers and bodies (screen sharing)
```

```bash
fenox phone calls                     # recent calls, newest first (last 30 days)
fenox phone calls --missed            # only the ones you missed
fenox phone calls --from 08031234567  # every call with one number
fenox phone calls --days 0            # the whole log, not just 30 days
fenox phone calls --from 08031234567 --dial   # call it back, after confirming
fenox phone calls --mark-read         # clear the "new call" flags shown
fenox phone calls --json
```

```bash
fenox phone contacts                  # the phone book, by name
fenox phone contacts --search queen   # by name or number
fenox phone contacts --export book.tsv
fenox phone calendar                  # the next 7 days, recurring events included
fenox phone calendar --days 30 --search retro
fenox phone calendar --add "Standup" --at 09:30
```

Numbers resolve to contact names, a call that never connected shows its length as
`—` rather than a misleading `0s`, and a withheld number is reported as unknown
rather than as the provider's placeholder. `--dial` needs `--from` and always asks
before it dials anything. Calendar events are read from the phone's *instances*
table, so a weekly meeting shows up every week it actually happens; `--add` needs
`--at` as `HH:MM` or `YYYY-MM-DD HH:MM`.

Message bodies are shown as they are by default; `--redact` replaces a number with
its last four digits and a body with its length, so the shape of a conversation is
visible without the content. Nothing is uploaded anywhere, and reading never marks
anything as read unless you pass `--mark-read`.

Inside the dashboard, the four **PHONE** rows on a device screen open the same
things as browsable screens: **Read messages** (`1`), **Read the call log** (`2`,
with a day-grouped list, a live count of unread messages and unheard voicemails,
and a per-call screen to call back, remove the call, or see that number's
history), **Read contacts** (`3`, searchable, and a per-contact screen that jumps
into the calls and messages with that person), and **Read the calendar** (`4`,
with add-event).

| What | Status |
| --- | --- |
| Messages: read, search, mark read, export | ✅ no root |
| Call log: read, filter, search, call back, remove, export | ✅ no root |
| Contacts: read, search, call, message, export | ✅ no root |
| Calendar: read, search, add, export | ✅ no root |
| Contacts, calendar | 🔜 next, same mechanism |
| Notifications, device control | 🔜 planned |
| Sending an SMS from the terminal | needs the optional companion app |

## 💾 Where Files Land

On WSL everything saves under `C:\Users\<you>\Desktop\Fenox\`, so it is viewable
from Windows. On plain Linux the same layout lives under `~/Fenox`.

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
| `fenox` | Opens the live interactive dashboard (single-keypress). |
| `fenox-connect` | ⚡ **One-shot connect**: connects all devices (USB + wireless, no prompts), explains stuck devices, binds all ports. `fenox-connect <device>` for one. |
| `fenox rename <old> <new>` | ✏️ **Rename device** — regenerates all aliases instantly. `m` in the menu does the same. |
| `fenox run myapp mydevice` | Standard launch. Use `all` as the device for Tmux blast deployment (`fenox run myapp all`). |
| `fenox run myapp mydevice --remote` | Launch targeting remote backend. |
| `fenox bind myapp mydevice` | Bind ports for a specific app/device. |
| `fenox build myapp` | Build release APK. |
| `fenox logs myapp mydevice` | Stream app-specific logs. |
| `fenox mirror mydevice` | Start Scrcpy mirroring. |
| `fenox pair` | Start Wireless Pairing Wizard. |
| `fenox doctor` | Run full system health check and restart. |
| `fenox init` | One-time setup. `--reset-settings` re-asks the questions. |
| `fenox uninstall` | Remove fenox, its config and its shell hooks. `--yes` skips the prompt, `--keep-config` keeps `~/.fenox.json`. |

## 🧹 Uninstall

```bash
fenox uninstall              # shows exactly what it will remove, then confirms
fenox uninstall --yes        # no prompt (for scripting)
fenox uninstall --keep-config  # keep ~/.fenox.json and your devices/apps
```

It removes the installed binary, the `fenox` symlink, the config, config backups
and the run history, and strips only its own hooks from `~/.bashrc` and
`~/.zshrc` — other lines in those files are left untouched. Running it from a
source checkout never deletes the checkout.

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

**Does it work on macOS or Windows natively?** No. Fenox targets Linux and WSL:
the installer refuses on macOS and on any other operating system rather than
installing a Linux binary that cannot run. There is no native Windows build — on
a Windows machine, run fenox inside WSL.

**Does it need a Python toolchain?** No. The installers fetch a self-contained
binary. Python 3.8+ is only needed to build from source or to write plugins.

**Where is my data?** Everything is local: `~/.fenox.json` (devices, apps,
groups), `~/.fenox/` (plugins, profiles, hooks), `~/.fenox-backups/`. Use
`fenox profile export <name>` to move a setup between machines.

**How do I pin a version?** Built from a clone, edit `VERSION` so the installer
resolves that release's tag, then run `bash install.sh`.

**A device went offline and came back.** `fenox watch` re-binds reverse ports as
soon as a device reconnects, and `fenox sync` reconnects known devices on demand.

## 🤝 Contributing

Bug reports, fixes and documentation are all welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions and how releases are
cut, and [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

Please report security problems privately via
[SECURITY.md](SECURITY.md), and note that this project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md).