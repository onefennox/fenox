# Fenox

**Android device management and Flutter development, from a browser.**

Fenox is a single-user, self-hosted web app for Linux and WSL. Connect as many
phones as you like over wireless or USB debugging, drive them completely —
screen, input, apps, files, logs, diagnostics and the phone's own data — then
register your Flutter projects, run them on any connected device, watch them
live, and hot reload, hot restart or stop them without opening a terminal.

One process, one port. The dashboard, the REST API and the WebSockets are served
together, and the built web app is bundled into the Python package.

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/packaging/install.sh | bash
fenox
```

Then open <http://localhost:8787>.

---

## Status

**0.1.0 — all seven milestones are code-complete; device verification is in
progress.** Every milestone's exit criteria require a physical phone, so no
milestone is marked *done* yet. `ruff`, `mypy` and `pytest` (160 tests) are green.

This is a real product with real code — not a design phase — but it has not yet
been proven end to end on real hardware, and the [Known
limitations](#known-limitations) below is not a formality. Read it before you
rely on it.

| Phase | Scope | State |
| --- | --- | --- |
| M0 | Foundation: hub, owner auth, SQLite, packaging | done |
| M1 | Devices in the browser | code complete, device verification pending |
| M2 | Projects, run and hot reload | code complete, device verification pending |
| M3 | Device toolbox and phone data | code complete, device verification pending |
| M4 | In-browser mirroring | code complete, device verification pending |
| M5 | Access: LAN / tunnel / TLS / PWA | code complete, device verification pending |
| M6 | Onboarding, guided installs, diagnosis | code complete, device verification pending |

Progress per phase: [`docs/ROADMAP.md`](docs/ROADMAP.md). Design and rationale:
[`docs/SPEC.md`](docs/SPEC.md).

---

## What it does

**Devices**
- Plug-and-play over USB, wireless debugging and emulators; devices appear on
  their own and reconnect automatically.
- Full remote control: screenshots, recording, wake/lock, type, tap, swipe, key
  events, clipboard, open URL.
- Apps: list, install an APK, uninstall, clear data, force-stop, info, launch.
- Files: browse, download, push, pull, upload, make a directory, delete.
- Screen mirroring in the browser — video plus touch and keyboard control.
- Diagnostics: logcat stream, device info, battery, storage, processes,
  notifications, shell.
- Your phone's own data, read directly with no root and nothing installed on the
  phone: messages, calls, contacts, calendar.

**Flutter**
- Register projects by pointing at a folder — the backend port, API URLs and
  Android package are detected, not asked for.
- Run a project on any connected device and watch it live in a real terminal.
- **Hot reload, hot restart and stop that are actually Flutter's own** — the hub
  spawns `flutter run --pid-file` and sends `SIGUSR1` / `SIGUSR2` to that pid.
  Not stdin scraping, not VM internals.
- "Run on all devices" fans out to one session per device, shown as a live grid.
- Dart VM Service and DevTools links surfaced automatically.

**When something is wrong**
- `fenox doctor` explains it. Every problem is reported as *what* / *why* / *the
  exact command that fixes it* / *whether Fenox can run it for you* — and fixes
  say which shell they have to be pasted into.
- `fenox doctor --fix` attempts what it is allowed to attempt, verifies each
  attempt, and reports **fixed**, **narrowed it down**, **no change** or **this
  one needs you**. An action that did not work is never reported as a success.

---

## Requirements

| | |
| --- | --- |
| **OS** | Linux, or WSL2 on Windows 11 |
| **Python** | 3.11 or newer |
| **adb** | [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) |
| **Flutter** | To build and run apps. [Install guide](https://docs.flutter.dev/get-started/install/linux) |
| **scrcpy** | For screen mirroring |
| **ffmpeg** | Optional, for recording |

### About WSL and USB — please read

WSL has no USB passthrough of its own, and Microsoft does not implement one. USB
support in WSL is entirely third-party (`usbipd-win`). The practical
consequences, which Fenox handles for you:

- **Wireless debugging needs nothing installed on Windows.** Turn it on in
  Developer options, enter a six-digit code once per phone, and you are done.
  This is the recommended path on WSL.
- **USB on WSL needs the `usbipd-win` bridge, installed once per machine** with
  one Administrator PowerShell command. After that Fenox attaches and
  re-attaches the phone by itself — those attachments do not survive a reboot or
  an unplug/replug, and no third-party tool automates that part, so Fenox does.
- On native Linux, macOS and Windows, USB just works.

`fenox doctor` tells you which of these applies to your machine and, if the
bridge is missing, gives you the exact command.

---

## Install

### With uv or pipx — recommended

```bash
uv tool install "fenox @ git+https://github.com/onefennox/fenox"
# or
pipx install "fenox @ git+https://github.com/onefennox/fenox"
```

This is the most reliable route and the one to reach for if anything below
misbehaves. It clones straight from GitHub, so it is never affected by the CDN
caching described under the one-liner, and it installs Fenox isolated from your
system Python. Upgrade later with `uv tool upgrade fenox` or `pipx upgrade fenox`.

### One-liner (Linux / WSL)

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/packaging/install.sh | bash
```

This creates a private virtual environment under the data directory, puts a
`fenox` launcher on `PATH`, prints a report on your machine, and installs a
systemd user service.

> **If the one-liner misbehaves straight after a release, use the pinned form.**
> `raw.githubusercontent.com` is a CDN and keeps serving the previous copy of a
> file for a short while after a push — long enough that a freshly published
> installer can still contain the previous release's URLs. Pin the commit and the
> content is immutable:
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/$(git ls-remote https://github.com/onefennox/fenox main | cut -f1)/packaging/install.sh | bash
> ```
>
> `uv`/`pipx` and a plain `git clone` are unaffected, because they clone from
> GitHub rather than fetching a cached file.

To install system-wide instead, for a shared machine:

```bash
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/packaging/install.sh | sudo bash -s -- --system
```

which uses the usual FHS layout — code in `/usr/local/lib/fenox`, launcher in
`/usr/local/bin`.

### From a checkout

```bash
git clone https://github.com/onefennox/fenox.git
cd fenox
bash packaging/install.sh
```

### Why there is no Docker image

Fenox is deliberately not containerised, and it is worth saying why rather than
leaving you to wonder.

Fenox's entire job is to reach the host: the adb server listening on
`127.0.0.1:5037`, the USB device nodes under `/dev/bus/usb`, and the Flutter SDK
that builds your apps. On WSL it additionally depends on the `usbipd` bridge,
which runs on the Windows side of the machine and is not reachable from a Linux
container at all. A containerised Fenox would need `--network=host`,
`--device=/dev/bus/usb` and a mounted SDK just to see one phone, and would still
be blind to the WSL case — while the tools that *can* be containerised, because
they only proxy HTTP, gain nothing from it.

Running natively is also what makes the diagnosis engine possible: `fenox doctor`
inspects the real machine — real USB permissions, the real adb topology, the real
installed SDKs — which is the whole point of it.

If you need to reach the hub from another machine, that is a **reach** setting
(local / LAN / remote with TLS), not a container.

---

## Quick start

1. **Install** Fenox with either command above.
2. **Check your machine** — this is worth doing first, and it is the fastest way
   to get help later:

   ```bash
   fenox doctor
   ```

3. **Start the hub** and open the dashboard:

   ```bash
   fenox
   ```

4. **Connect a phone.** Go to **Connect** in the sidebar. Wireless debugging is
   the default and needs nothing installed; on the phone, turn on *Wireless
   debugging* in Developer options, then *Pair device with pairing code* and type
   the six-digit code into Fenox. It finds the phone's address by itself.
5. **Add your project.** **Projects → Add project** asks three questions: name,
   folder, backend link. The folder is chosen with a real file browser that marks
   Flutter projects, so nothing has to be typed by hand.

Then pick the project, pick your phone, and press **Run**.

---

## When something does not work

Run this first. It is designed to be pasted into a bug report:

```bash
fenox doctor
```

```
fenox 0.1.0 — 1 problem needs fixing
platform wsl · python 3.12.3

Problems
  [ERROR] SAMSUNG Mobile USB Remote NDIS Network Device is held by a stale usbipd export
          Attaching fails with "Device busy (exported)". usbipd is holding an
          export for this device that no longer resolves...
          fix — in an Administrator PowerShell on Windows:
            $ usbipd unbind --busid 1-2
            $ usbipd bind --busid 1-2
            $ usbipd attach --wsl --busid 1-2
```

| Flag | |
| --- | --- |
| `fenox doctor` | Human-readable, identifiers masked, exits non-zero if broken |
| `fenox doctor --json` | Machine-readable |
| `fenox doctor --full` | Do not mask home paths, serials or addresses |
| `fenox doctor --fix` | Run the automatic fixes, verify each one, then report |

**Do not run `adb kill-server` to fix a connection problem.** It disconnects
every device you have and, on WSL, takes the USB attachment down with it. Fenox
detects that state and says so.

The same findings appear in the dashboard, on the **Connect** page, with a
copy-to-clipboard button and a **Let Fenox fix this** button for anything Fenox
can do without administrator rights.

---

## Configuration

Set through the web app's Settings page, the CLI, or the environment.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FENOX_HOST` | `127.0.0.1` | Bind address |
| `FENOX_PORT` | `8787` | HTTP port |
| `FENOX_DATA_DIR` | `$XDG_DATA_HOME/fenox` | Data and database location |
| `FENOX_LOG_LEVEL` | `info` | `debug` for the full connection log |
| `FENOX_TLS_CERT` / `FENOX_TLS_KEY` | — | TLS, required before binding beyond localhost |

Data lives in `$FENOX_DATA_DIR`: `fenox.db` (SQLite, WAL), `auth.json` (mode
`0600`), per-session transcripts, logs and backups. On first start Fenox imports
`~/.fenox.json` if it is there, leaving the original alone.

### Reach

By default Fenox binds `127.0.0.1` and is reachable only from the same machine —
on WSL that includes your Windows browser, so ordinary use needs no setup.
Settings can widen this to the local network, and remote access is deliberately
opt-in and refuses plain HTTP. TLS is required for anything beyond localhost.

## CLI

```
fenox                  Start the hub and open the dashboard
fenox serve            Start the hub headless (systemd, remote servers)
fenox doctor           Report on this machine and what to fix
fenox auth reset       Recover the owner credential
fenox info             Configuration and environment
fenox settings         Show reach, port and URLs
fenox config list      Read or write a setting
fenox service install  Install the systemd user service
fenox update           Update to the latest version
```

## Security

Fenox is treated as what it is: a tool that can run commands on your machine, in
the same category as Jupyter, not as a website.

- **Single owner, login only.** There is no registration route and no user list
  anywhere in the app. The password is stored as an argon2 hash; sessions are
  signed, `httpOnly`, `SameSite=Lax` cookies, and mutations carry a CSRF token.
- **Lockout recovery is CLI-only** (`fenox auth reset`). There is no
  network-reachable override.
- **Everything past the login is authenticated**, including the diagnostics
  endpoints, which report on the host filesystem and are therefore as sensitive
  as a shell.
- **No telemetry, and no analytics.** Nothing about you, your devices or your
  usage is sent anywhere. The one outbound request Fenox ever makes is fetching
  the pinned `scrcpy-server` release from GitHub the first time you use screen
  mirroring; it carries a `User-Agent` and nothing about your machine. Set
  `FENOX_SCRCPY_SERVER` to a local file to avoid even that, and it works fully
  offline once cached.
- **Nothing is escalated.** Fenox never runs `sudo` and never triggers a UAC
  prompt. Where administrator rights are genuinely required, it returns the
  command for you to run and says where to run it.

---

## Development

```bash
bash scripts/dev.sh          # install into .venv and serve with reload

.venv/bin/pytest -q          # tests
.venv/bin/ruff check src tests
.venv/bin/mypy
```

The web application lives in `web/` and builds into the Python package:

```bash
cd web && npm install && npm run build   # outputs to src/fenox/web
cd web && npm run dev                    # dev server on :5173, proxying to :8787
```

### Layout

```
src/fenox/
  core/     the engine — no web framework, no argparse, no terminal UI
    config · db · host · env · log      the machine and its configuration
    adb · devices · connect · usbipd     talking to phones, and why it fails
    projects · flutter · sessions       running apps and reloading them
    toolbox · files · phone · mirror    what you can do to a device
    doctor · report · access · auth     diagnosis, reach, the owner credential
  server/   FastAPI adapters over core
  cli/      argparse management surface
  web/      the built SPA (generated — do not edit)
web/        React + TypeScript + Vite source
```

`core` never imports `server` or `cli`. The layering is enforced by review and is
worth keeping: it is what makes the same engine usable from a browser, a terminal
and a test.

### Tests

```bash
.venv/bin/pytest -q
```

The suite runs on Linux, macOS and Windows. It covers the `usbipd` output parser
and the diagnosis engine against recorded fixtures, so the platform branches can
be verified from any platform — which matters, because the whole point of the
diagnosis engine is to be right about *other people's* machines.

CI also asserts that `fenox doctor` **fails** on a runner with nothing installed.
A report that says "all fine" on a broken machine is worse than no report, and
that regression is now a build failure rather than something a reviewer has to
notice.

---

## Known limitations

Stated plainly, because you would find them anyway.

- **Not yet verified on real hardware, end to end.** Every milestone's exit
  criteria need a physical phone. The automated tests use fakes for `adb` and
  `flutter`; real-device behaviour is unproven.
- **Linux and WSL only.** macOS and native Windows are not supported yet. The
  engine is written to be platform-agnostic — findings are keyed by *problem*,
  and fixes declare which shell they belong in — but the platform-specific work
  for macOS and Windows has not been done.
- **No multi-device concurrent Flutter runs are proven.** Sessions fan out and
  each is independent, but this has not been exercised with several phones.
- **Screen mirroring is video and control only.** Audio needs scrcpy ≥ 2.0.
- **Mirroring is the most version-sensitive feature.** It reads scrcpy's socket
  framing directly rather than using `@yume-chan/scrcpy`, which keeps the
  dependency surface small but makes it sensitive to the scrcpy version.
- **The release pipeline is minimal.** Nothing is published to PyPI, and there is no
  Homebrew formula, `winget` package or `apt` repository, so installing means a
  git URL. Nothing is code-signed either.

## License

MIT — see [`LICENSE`](LICENSE).
