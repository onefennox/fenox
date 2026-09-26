# Fenox — product & architecture specification

> Status: **draft for approval.** This document is the single source of truth for
> the rebuild. No code is written until it is agreed. It supersedes the earlier
> `WEB_APP_PLAN.md` in the `fenox-mobile` repo.

---

## 1. One-line product statement

**Fenox is a single-user, self-hosted web app that connects to Android phones
over USB or wireless debugging and lets a Flutter developer manage every device
in full and run, watch, and hot-reload their Flutter apps — all from the
browser, without touching the command line.**

## 2. Product vision

Someone installs Fenox from GitHub on their Linux/WSL machine. They open the web
app in a browser. They connect as many phones as they want (USB or wireless).
They can then:

1. **Manage each device completely** — screen mirroring and control, screenshots
   and recording, typing/tapping/swiping, app install/uninstall/clear/stop, file
   push/pull/browse, device info/battery/network/storage/processes, notifications,
   and their phone's own data (messages, calls, contacts, calendar) — everything
   the current CLI can do, and more, with nothing but the browser.
2. **Register Flutter projects** — point at a project directory, set the backend
   service URLs (local and remote), and save.
3. **Run a project on any connected device, live** — watch the app on the phone,
   stream `flutter run` output into the browser terminal, then **hot reload, hot
   restart, stop, and open DevTools**, exactly as if the terminal were in front of
   them.

The command line does not disappear: it becomes a second front end over the same
core, for power users and scripts. The browser is the product.

## 3. Target user

- A **Flutter developer** working from Linux or WSL who owns one or more physical
  Android phones and is tired of juggling `adb`, `flutter run`, scrcpy, and a
  pile of terminal windows.
- A **tester / non-developer** who needs to install a build, drive a phone, or
  check something on it, and does not want a terminal at all.

## 4. Naming & distribution

| | |
| --- | --- |
| Product name | **Fenox** |
| Repo / org | `onefenox/fenox` |
| Install | GitHub → one curl command, `uv tool`, `pipx`, or from a checkout |
| Runtime | one process, one port |
| Platform | Linux + WSL (matches today's product); macOS/Windows out of scope for v1 |

Install paths (mirrors how OmniRoute is distributed):

- **curl one-liner** — `curl -fsSL https://raw.githubusercontent.com/onefenox/fenox/main/packaging/install.sh | bash`.
  Downloads a checksum-verified release, sets up a private venv under the data
  dir, installs a launcher on `PATH`, optionally installs the systemd user service.
- **systemd `--user`** — `systemctl --user enable --now fenox` keeps the hub alive
  across reboots.
- **`uv tool install` / `pipx install`** — the shortest path for anyone who
  already uses either, and it keeps Fenox isolated from system Python.
- **From source** — `git clone && bash packaging/install.sh` for contributors.

**No container image, deliberately.** Fenox's whole purpose is to reach the host:
the adb server on `127.0.0.1:5037`, the nodes under `/dev/bus/usb`, and the
Flutter SDK that builds the apps. On WSL it also depends on the `usbipd` bridge,
which lives on the Windows side of the machine and is unreachable from a Linux
container. A container would need `--network=host`, `--device=/dev/bus/usb` and a
mounted SDK merely to see one phone, and would still be blind to the WSL case.
It would also undermine `fenox doctor`, whose value is inspecting the real
machine. Tools that only proxy HTTP can be containerised and gain nothing by it.
Remote access is a **reach** setting with TLS, not a container.
- **PWA** — the dashboard is installable to a home screen (later phase).

## 4a. Connecting a device, honestly

The product promise is that connecting a phone needs no terminal. That is true,
with one documented exception, and the exception is worth stating plainly rather
than discovering later.

| Path | What the owner has to do |
| --- | --- |
| **Wireless debugging** (Android 11+) | Turn it on in Developer options and enter a six-digit code **once per phone per machine**. Nothing is installed on the computer. |
| **USB on Linux / macOS / Windows** | Plug it in. The OS exposes the device to adb directly. |
| **USB on WSL2** | One-time, per machine: install `usbipd-win` (needs administrator). After that Fenox attaches and re-attaches by itself. |

**Why WSL is different.** WSL has no USB passthrough, and Microsoft does not
implement one — USB support in WSL is entirely third-party (`usbipd-win`). Two
properties of that bridge dictate the design:

- `usbipd bind` **persists** across reboots but needs **administrator** rights.
- `usbipd attach --wsl` needs **no** rights but is **not persistent**: it must be
  redone after every reboot, device reset, or unplug/replug.

So the recurring part is automatable and the one-time part is not. Fenox performs
every `attach` itself, on a timer, so replugs and reboots are uneventful; and it
reports the single `bind` command when a device has never been shared. It never
runs anything that would raise a UAC prompt on the owner's desktop.

**Wireless is the default** for exactly this reason: it is the only path with no
host setup at all, on any platform.

**Auto-connect is a platform feature, not something Fenox fakes.** adb
auto-connects any device whose GUID it has paired, whenever that device publishes
`_adb-tls-connect`. On Platform Tools 37 / Android 17 ("ADB Wi-Fi 2.0") the network
itself is remembered as trusted, so a paired phone reconnects by itself after
sleep, a reboot, or a change of network. Fenox detects the adb release and says so
when an upgrade would remove work rather than pretending the current setup is
equivalent.

**Pairing is discovered, not typed.** A phone publishes `_adb-tls-pairing` only
while its "Pair device with pairing code" dialog is open — precisely when the
owner is looking at the code. Fenox watches for it and offers the address
pre-filled, so the IP and port are never typed. `adb mdns services` is the
mechanism, and it needs mDNS to work on the network; where it is filtered, the
manual fields remain as a fallback.

**Silence is a bug.** A phone that is plugged in, authorised and healthy but not
bridged into WSL is indistinguishable from no phone at all. Fenox therefore
reports *findings* — what is wrong, why, and the one command that fixes it —
rather than a bare "0 devices", on the Connect page and in the hub log alike.

## 5. Runtime model

```
fenox                 # start the hub, open the dashboard in a browser
fenox serve           # start the hub headless (no browser), for services
fenox --version       # fast, no server, no adb
fenox <subcommand>    # management/ops from the terminal (see below)
```

- The hub serves the REST API, the WebSocket endpoints, and the built SPA from
  **one process on one port** (default `8787`).
- Starting the hub does **not** block the CLI: it runs in the foreground and
  stops on Ctrl+C; under systemd it runs as a service.
- `fenox` (no args) starts the hub and opens `http://localhost:8787`.

**The terminal is the management surface; the web is the product.** The CLI covers
setup and operations the way comparable tools do — `help`, `serve`, `init`,
`doctor`, `auth reset`, service/update information, and scriptable device/project
management for automation. The rich, live, day-to-day workflows (running apps,
hot reload, mirroring, browsing device data) are browser-first. A full-screen
terminal dashboard is not the goal; a capable, scriptable CLI is.

## 5a. Technology stack

Locked after comparing with how comparable tools (notably OmniRoute) are built.
The frontend and data choices match that modern standard; the backend stays
Python because the device engine is inherently OS-level (adb, pty, signals, WSL)
and already exists and is tested.

| Layer | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Web framework | FastAPI + uvicorn (ASGI) |
| Realtime | Native WebSocket over uvicorn |
| Database | **SQLite** via the standard-library `sqlite3`, with numbered migrations |
| Frontend | React 19 + TypeScript + Vite (SPA), Tailwind CSS 4 |
| Server state | TanStack Query (Zustand was specified but is not used) |
| Terminal | xterm.js (web) |
| Mirroring client | Native `<video>` + Media Source Extensions; `ffmpeg` remuxes on the hub (§10a) |
| CLI | argparse + Rich (management surface) |
| Quality | pytest, Ruff, mypy, coverage gate; Playwright for web end-to-end |
| Packaging | curl installer, `uv`/`pipx`, systemd `--user`/`--system`; PWA later |

Layering is strict: `core` has no web framework, no argparse and no terminal UI.
`server` and `cli` are independent adapters over `core`.

## 6. Architecture

```
Browser (desktop / phone / LAN)
   │  HTTPS/HTTP · WebSocket
   ▼
┌───────────────────────────────────────────────────────────────┐
│  Fenox hub  (single Python process)                           │
│                                                               │
│  server/   FastAPI · REST · WebSocket · static SPA · auth     │
│  core/     the engine (see §7)                                │
│    config · host · adb · devices · projects · flutter         │
│    sessions · phone · mirror · doctor · auth                  │
│                                                               │
│  Long-lived children: flutter run (pty), scrcpy-server, adb   │
└───────┬───────────────────────────────┬───────────────────────┘
        │ adb (shared server, port 5038) │ pty / signals / TCP
        ▼                                ▼
   USB / wireless phones            Flutter SDK · scrcpy
```

**Layering rule:** `core/` never imports `server/` or `cli/`. `server/` and
`cli/` are both thin adapters over `core/`. The engine has no web, no argparse,
and no Rich UI dependency.

### Repository layout

```
fenox/
  pyproject.toml
  VERSION
  README.md
  docs/SPEC.md
  src/fenox/
    __init__.py
    __main__.py
    version.py
    core/
      config.py       # data dir, config schema, atomic save, migration
      db.py           # SQLite (WAL) + numbered migrations
      host.py         # platform/WSL, adb.exe, output dirs, run_cmd
      adb.py          # shared server, device list, connect, pair, mdns, reverse
      devices.py      # registry, telemetry, autodetect, watcher, health
      projects.py     # project CRUD, scan, port/URL/package detection, groups
      flutter.py      # flutter binary, build, install, open, run args
      sessions.py     # run supervisor: pty, pid-file, signals, streams, history
      session_io.py   # pty transcript read/write helpers for sessions
      toolbox.py      # screen input, apps, power, clipboard, notifications
      files.py        # device file browse / push / pull / mkdir / delete
      phone.py        # content providers: messages, calls, contacts, calendar
      mirror.py       # scrcpy-server -> adb reverse -> ffmpeg fMP4 (§10a)
      scrcpy_server.py  # pin/provision the scrcpy-server jar
      access.py       # reach tiers: localhost / LAN / remote, TLS
      doctor.py       # environment checks + guided tool installs
      auth.py         # single-owner credential + sessions
    server/
      app.py          # FastAPI app factory, lifespan, static mount
      routes/         # system, devices, projects, runs, settings, auth,
                      #   phone, files, mirror, toolbox
      ws.py           # /ws/events, /ws/runs/{id}
      security.py     # auth middleware, CSRF, token, bind/reach rules
    cli/
      main.py         # argparse + dispatch
    web/              # built SPA (generated from ../web — do not edit)
  web/               # React + TS + Vite SPA (own package.json)
  tests/
  packaging/
    install.sh
    fenox.service
    uninstall.sh
  scripts/
    dev.sh
  .github/workflows/
```

> The engine is **ported from `fenox-mobile/src/fenox.py`**, not rewritten. The
> adb/WSL topology and the phone content-provider readers encode real-device
> quirks and are moved behind the `core` API with their tests.

## 7. Core engine API (draft surface)

Each module exposes plain Python functions/classes. Illustrative, not final.

**`config`**
- `data_dir() -> Path` — `$FENOX_DATA_DIR` → `$XDG_DATA_HOME/fenox` → `~/.local/share/fenox`.
- `load() -> Config`, `save()` (atomic + rolling backups), `migrate_legacy()` (`~/.fenox.json`).
- Live maps: `devices`, `projects`, `groups`, `settings`, `owner`.

**`host`**
- `is_wsl`, `windows_user`, `find_windows_adb()`, `adb_exe`, output dirs, `run_cmd()`.

**`adb`**
- `ensure_server()`, `connected_ids()`, `pending()`, `connect(ip, port)`, `pair(ip, port, code)`,
  `mdns_candidates()`, `mdns_port(ip)`, `reverse(serial, ports)`, `shell(serial, cmd)`.

**`devices`**
- `register/rename/enable/disable/remove`, `telemetry(serial)`, `telemetry_many()`,
  `autodetect()`, `autodetect_wireless()`, `check_and_connect(alias)`, `DeviceWatcher`.

**`env`** — every fact about the machine, answered once
- `tool(name, settings) -> Tool`, `tools()`, `invalidate()`, `adb_topology()`,
  `shell()`, `fix_runs_in()`, `summary()`.
- The single owner of tool resolution and version parsing. This exists because
  two copies of the adb version parser existed and the product answered the same
  question two ways — the doctor reporting the frozen protocol string
  `1.0.41` while the connection layer reported the real release `36.0.0`. Probes
  are cached, because the dashboard asks often and each one may run a subprocess.

**`report`** — the shareable diagnosis artefact
- `build(settings, store) -> dict`, `render(report) -> str`, `redact(text)`.
- Assembled as data, not printed inline, so the terminal, `--json` and a future
  web view are three renderings of one answer and can be tested.
- Redaction is the default: home directories, Windows account names, device
  serials and IP addresses are masked, because these reports get pasted into
  forums. `--full` disables it for reading locally. Secrets are never included.
- `fenox doctor` exits non-zero only for findings that actually block a device,
  so advice (an out-of-date adb) never reads as a broken machine.

**`connect`** — why a device is not reachable, and what to do about it
- `diagnose() -> [Finding]`, `repair(finding)`, `repair_usbipd()`.
- A `Finding` is `{id, severity, title, detail, fix, auto, scope, also, runs_in}`.
  `id` is the **problem** (`usbipd.stale_export`), never the instance, so
  consumers can rely on it; `scope` says which device. `runs_in` is `"windows"`
  when the fix has to be pasted into a Windows PowerShell even though the user is
  looking at a bash prompt.
- Diagnosis is strictly read-only. It reports what previous attach attempts
  recorded rather than trying an attach to find out.
- Identifiers are **problem keys**, so the same key means the same thing on every
  platform: `adb.missing`, `adb.too_old`, `usbipd.missing`, `usbipd.unbound`,
  `usbipd.not_attached`, `usbipd.stale_export`, `device.unauthorized`,
  `device.stale_adb_entry`.
- `device.stale_adb_entry` exists because the obvious reflex — restarting the adb
  server — disconnects every device and, on WSL, takes the USB attachment down
  with it. The finding says so explicitly.
- An unfixable-by-us failure is logged **once**, not on every poll; repeats drop
  to debug. A tool people leave running must not fill its own console.

**`usbipd`** (WSL only) — the USB/IP bridge, and the whole of Fenox's knowledge of it
- `installed()`, `version()`, `list_devices() -> [UsbipdDevice]`, `android_devices()`,
  `find_device(busid)`, `attach(busid)`, `detach(busid)`, and the command builders
  `bind_command` / `attach_command` / `unbind_command` / `install_command`.
- `bind` needs administrator rights and is therefore only ever *returned* as a
  command for the owner. `attach` needs none, and is done by Fenox.

**`projects`**
- `add/update/remove/scan`, `detect_port()`, `detect_backend()`, `package_name()`,
  `groups`, `aliases()`, `completions()`.

**`flutter`**
- `which_flutter()`, `build_release(project)`, `install_apk()`, `open_app()`, `run_argv(project, device, remote)`.

**`sessions`** — see §9.

**`phone`** — `threads()`, `messages()`, `calls()`, `contacts()`, `calendars()`, `events()`,
`add_event()`, `mark_read()`, `dial()`.

**`mirror`** — see §10.

**`doctor`** — `checks() -> [Check]`, `install(tool)` (guided), `flutter_adb_mismatch()`.

**`auth`** — `has_owner()`, `set_owner(password)`, `verify(password)`, `issue_session()`,
`verify_session(cookie)`, `reset()`.

## 8. HTTP API (v1)

All routes are JSON and require an authenticated session except
`/api/setup*`, `/api/auth/*`, and static assets.

```
# setup + auth
GET    /api/setup                      is the owner configured?
POST   /api/setup                      set owner password (first run only)
POST   /api/auth/login                 {password} -> session cookie
POST   /api/auth/logout
GET    /api/auth/me
POST   /api/auth/token                 rotate/issue a bearer token (for scripts)

# system
GET    /api/system                     doctor: tools, versions, adb server, platform
POST   /api/system/install             guided install of a missing tool (confirmed)
GET    /api/system/logs                recent hub log

# settings
GET    /api/settings                   reach, port, remote domain, output dirs
PATCH  /api/settings                   change reach / port / domain (confirmed)

# devices
GET    /api/devices                    registered + discovered, with health
POST   /api/devices/discover           trigger USB/mDNS scan
POST   /api/devices/{id}/connect
POST   /api/devices/{id}/pair          {ip, port, code}
PATCH  /api/devices/{id}               rename / enable / edit
DELETE /api/devices/{id}
GET    /api/devices/{id}/telemetry
GET    /api/devices/{id}/screenshot
POST   /api/devices/{id}/shell
GET    /api/devices/{id}/files?path=   browse / download
POST   /api/devices/{id}/files         push
GET    /api/devices/{id}/apps          list / install / uninstall / clear / force-stop
GET    /api/devices/{id}/logcat        stream (also over WS)
POST   /api/devices/{id}/mirror        start mirror session
WS     /ws/mirror/{id}                 scrcpy video/audio/control proxy
GET    /api/devices/{id}/phone/{resource}   messages/calls/contacts/calendar

# projects
GET    /api/projects
POST   /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}
POST   /api/projects/scan              auto-register under the projects dir

# runs
POST   /api/runs                       {project, device, mode: local|remote}
GET    /api/runs                       active + recent
GET    /api/runs/{id}
POST   /api/runs/{id}/reload           SIGUSR1
POST   /api/runs/{id}/restart          SIGUSR2
POST   /api/runs/{id}/stop
WS     /ws/runs/{id}                   stdout stream + status
WS     /ws/events                      devices / projects / sessions / telemetry
```

## 9. Sessions & hot reload (the core feature)

This is what makes Fenox real, so it gets the most design attention.

`flutter run` supports `--pid-file <f>` and, once handlers are installed, responds
to **SIGUSR1 = hot reload** and **SIGUSR2 = hot restart**. Verified on this
machine. That is Flutter's own supported control path — not stdin scraping, not
VM-internals coupling.

```
POST /api/runs {project, device, mode}
  1. resolve device (core.devices.check_and_connect)
  2. adb reverse the project's port + additional ports
  3. spawn under a pty:
       flutter run -d <serial> --pid-file <tmp>
         --dart-define=API_BASE_URL=… [--dart-define=SOCKET_BASE_URL=…]
  4. stream stdout/stderr to subscribers (WS), keep a ring buffer
  5. poll the pid-file -> mark session running -> enable Reload/Restart
  6. parse stdout for the Dart VM Service URL and DevTools URL -> surface links
  7. reload  = kill -USR1 <pid>
     restart = kill -USR2 <pid>
     stop    = SIGINT, then SIGTERM, then reap
  8. on exit: record to history, mark finished/crashed
```

- A **pty** is used so ANSI colours, spinners, and the `flutter run` prompt render
  correctly in xterm.js. Control does not depend on the pty — signals do.
- **Multi-device:** each `(project, device)` pair is its own session. "Run on all"
  fans out to N sessions shown as a live log grid.
- **Orphans:** the supervisor stamps its children; on boot it marks any recorded
  running session whose process is gone as dead, and offers `--reap`. Under
  systemd, `KillMode=mixed` so children are not orphaned on restart.
- **Concurrency:** queue with a configurable cap; show resource use.

## 10. Mirroring (M-late, but fully in scope)

> **Superseded by implementation.** The design below is the original WebCodecs
> plan. The shipped design is recorded in §10a.

- The hub runs the **unmodified scrcpy-server** matching the installed scrcpy,
  pushed to the device and started over adb — no forked protocol.
- The hub sets up `adb forward`, opens the video/audio/control sockets, and
  **proxies bytes over WebSocket** (Python asyncio). It never decodes video.
- The browser parses with **`@yume-chan/scrcpy`** and renders via **WebCodecs**
  (`scrcpy-decoder-webcodecs`). Control events travel back over the same socket.
- scrcpy-server version is pinned and verified at connect time.
- **Note:** the dev machine currently has **scrcpy 1.25**; audio forwarding needs
  scrcpy ≥ 2.0. Phase 5 either upgrades scrcpy or ships video+control first.

## 10a. Mirroring — as built

An earlier WebRTC design (`scrcpy H.264 → ffmpeg → MediaMTX`) was tried and
abandoned. The shipped pipeline is deliberately simpler and has no extra ports
and no negotiation:

```
device H.264 (Annex B, untouched)
   → adb reverse: device connects back to the hub's listening socket
   → ffmpeg: remux only, to fragmented MP4
   → hub WebSocket (the same one the app already uses)
   → browser Media Source Extensions
   → native <video> element
```

- **The hub never decodes video**, and never transcodes — ffmpeg only remuxes.
  The device's hardware H.264 reaches the browser byte-for-byte.
- The reverse tunnel is the one the scrcpy server expects: the hub listens, maps
  the device's abstract socket to it with `adb reverse`, and the server connects
  back.
- **No WebRTC, no MediaMTX, no second port.** The mirror works wherever the app
  itself works, including behind a reverse proxy on a LAN.
- `@yume-chan/scrcpy` and `scrcpy-decoder-webcodecs` are **not** dependencies.
  Input does not travel the video socket: it reuses the toolbox action paths, so
  one code path drives the device whether or not mirroring is active.
- Fragments are emitted on a timer rather than only at keyframes, so latency does
  not depend on the phone producing frequent keyframes.
- **Audio is still open** and needs scrcpy ≥ 2.0; the installed server is 1.25.

## 11. Authentication & security

**Single owner. Login only. No registration, no user list, no roles.**

- First run shows a **setup wizard**: the owner sets a password once.
- Password stored as a salted hash (argon2 preferred; bcrypt fallback) in the data
  dir. There is no `/register` route anywhere in the app.
- Login issues a signed, httpOnly, `SameSite=Lax` session cookie; mutations also
  carry a CSRF token. Optional "trust this browser for 30 days".
- Lockout recovery is a CLI escape hatch: `fenox auth reset`. Never lock the owner out.
- **Reach** is configurable from Settings, in the same three tiers as before:
  1. **This machine only** (default) — bind `127.0.0.1`. On WSL the Windows browser
     reaches it via localhost forwarding, so normal use needs no setup.
  2. **Local network** — flip to `0.0.0.0`, show the URL(s), require the login and a token.
  3. **Remote / internet** — off by default; via a built-in tunnel or the owner's own
     reverse proxy/Tailscale, always over TLS. Plain `0.0.0.0` over the internet is refused.
- The hub can run arbitrary commands, so it is treated like Jupyter, not a website.

## 12. Data & storage

- **Data dir:** `$FENOX_DATA_DIR` → `$XDG_DATA_HOME/fenox` → `~/.local/share/fenox`.
- **Env config:** `FENOX_PORT` (8787), `FENOX_HOST` (127.0.0.1), `FENOX_DATA_DIR`,
  `FENOX_LOG_LEVEL`.
- **Database:** `fenox.db` (SQLite, WAL mode) with numbered migrations. Tables:
  `settings` (key/value JSON), `devices`, `projects`, `groups`, `runs`,
  `run_events`, and `schema_version`. The CLI and the hub share one database;
  SQLite's locking keeps concurrent access safe.
- **Files:** `auth.json` (owner hash, signing secret, script token, mode `0600`),
  `sessions/<id>/` (pty transcripts), `logs/`, `backups/`.
- **Migration:** on first start, import `~/.fenox.json` / `~/.fenox_history.json`
  if present, leaving the originals in place.

## 13. Frontend

React + TypeScript + Vite + Tailwind (shadcn/ui). TanStack Query for server state,
**xterm.js** for the run terminal and logcat. The mirror plays in a native
`<video>` fed by Media Source Extensions (see §10a).

Pages:

1. **Setup / Login** — first-run password, then login.
2. **Dashboard** — devices + projects at a glance, active runs, one-click Run.
3. **Devices** — list, connect, pair, rename, health.
4. **Device detail** — mirror, screenshot, files, shell, apps, logcat, phone data.
5. **Projects** — list, add/scan, backend + URL config.
6. **Project detail** — run targets, run history.
7. **Run** — live terminal, Reload / Restart / Stop, DevTools link, status.
8. **Setup (system)** — doctor, install missing tools.
9. **Settings** — reach, port, remote domain, token, theme.

The built SPA is bundled and served by the hub, so there is one artefact.

## 14. Testing strategy

- **Engine:** the existing tests move with the code (`test_device_detect`,
  `test_phone_content`, `test_version_key`, plus new unit tests per module).
- **Server:** FastAPI `TestClient` tests for routes, auth, and session lifecycle,
  with adb/flutter faked.
- **Sessions:** a fake "flutter" script that installs signal handlers and writes a
  pid-file, so reload/restart/stop are tested without a real SDK.
- **CLI:** the pty session-UI tests stay, now against the ported `cli/`.
- **E2E:** the release installer test stays, extended to verify `fenox serve`
  boots and `/api/system` responds.

## 15. Milestones (delivery order; full scope, no feature cuts)

| # | Deliverable | Exit criteria |
| --- | --- | --- |
| **M0. Foundation** | repo, `core` package boundary, `fenox serve` serving a skeleton SPA, XDG config + migration, auth setup/login, installer + service | install → open browser → set password → log in → see a real (if empty) dashboard; CLI still works |
| **M1. Devices** | connect/pair/list/manage, live status + telemetry, plug-and-play watcher | connect a phone over USB and over wireless, see it, rename it, watch it go offline/online live |
| **M2. Run + hot reload** | projects CRUD, run sessions, live terminal, Reload/Restart/Stop, DevTools link, multi-device fan-out | run a real Flutter app from the browser and hot-reload it |
| **M3. Device toolbox** | screenshots, files, shell, app list/install/uninstall, logcat, phone data | full parity with today's device screen |
| **M4. Mirroring** | in-browser video + control, audio, clipboard, multi-device | usable latency; touch/keyboard drive the phone |
| **M5. Access** | Settings-driven local/LAN/tunnel, TLS, PWA install | reach the hub from another machine and from a phone, safely |
| **M6. Onboarding** | tool detection + guided/automated installs, Windows-side guidance | a fresh machine reaches "running app" without a terminal |

**M2 is the reason to build this. M4 is the biggest cost. Neither blocks the other.**

## 16. Non-goals (v1)

- macOS and native Windows support.
- Multi-user / teams / accounts (single owner by design).
- iOS devices (adb/Android only).
- A plugin marketplace (the existing local plugin hook can stay simple).
- Hosting/managed cloud.

## 17. Decisions locked

- Rebuild the **shell**; **port the engine** (do not rewrite adb/phone logic).
- Product is **server-first**: one process, one port; browser is the front door.
- **Single owner** login; no registration, no user management.
- Frontend: **React + TS + Vite + Tailwind + xterm.js**.
- Distribution: **curl installer + `uv`/`pipx` + systemd (`--user` or `--system`)**,
  no container image, PWA later.
- Storage: **XDG data dir + env config**, migrate `~/.fenox.json`.
- Reach: localhost default; LAN/remote explicit, same login, TLS required off-localhost.

## 18. Resolved decisions

1. First-run setup: **web wizard** — install, open the browser, set the owner password on screen.
2. Lockout recovery: **`fenox auth reset` CLI only** — no network-reachable override.
3. Mirroring: **video + control first** (M4); audio follows after an scrcpy ≥ 2.0 upgrade.
4. Frontend: **`web/` in this repo**, built and bundled into the hub.
5. Terminal: **management/ops surface** (help, serve, init, doctor, auth reset,
   scriptable device/project management); the **web is the primary product**. No
   full-screen TUI dashboard.
