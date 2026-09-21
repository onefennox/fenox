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
| Install | GitHub → one curl command, or Docker, or from source |
| Runtime | one process, one port |
| Platform | Linux + WSL (matches today's product); macOS/Windows out of scope for v1 |

Install paths (mirrors how OmniRoute is distributed):

- **curl one-liner** — `curl -fsSL https://raw.githubusercontent.com/onefenox/fenox/main/packaging/install.sh | bash`.
  Downloads a checksum-verified release, sets up a private venv under the data
  dir, installs a launcher on `PATH`, optionally installs the systemd user service.
- **systemd `--user`** — `systemctl --user enable --now fenox` keeps the hub alive
  across reboots.
- **Docker** — `docker run -p 8787:8787 ...` for a headless server/remote host.
- **From source** — `git clone && ./scripts/dev.sh` for contributors.
- **PWA** — the dashboard is installable to a home screen (later phase).

## 5. Runtime model

```
fenox                 # start the hub, open the dashboard in a browser
fenox serve           # start the hub headless (no browser), for services/Docker
fenox --version       # fast, no server, no adb
fenox <subcommand>    # management/ops from the terminal (see below)
```

- The hub serves the REST API, the WebSocket endpoints, and the built SPA from
  **one process on one port** (default `8787`).
- Starting the hub does **not** block the CLI: it runs in the foreground and
  stops on Ctrl+C; under systemd/Docker it runs as a service.
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
| Frontend | React + TypeScript + Vite (SPA), Tailwind CSS |
| Server state / UI state | TanStack Query / Zustand |
| Terminal | xterm.js (web) |
| Mirroring client | `@yume-chan/scrcpy` + WebCodecs (video/audio/control) |
| CLI | argparse + Rich (management surface) |
| Quality | pytest, Ruff, mypy, coverage gate; Playwright for web end-to-end |
| Packaging | curl installer, systemd `--user`, Docker; PWA later |

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
    core/
      config.py      # data dir, config schema, atomic save, migration
      host.py        # platform/WSL, adb.exe, output dirs, run_cmd
      adb.py         # shared server, device list, connect, pair, mdns, reverse
      devices.py     # registry, telemetry, autodetect, watcher, health
      projects.py    # project CRUD, scan, port/URL/package detection, groups
      flutter.py     # flutter binary, build, install, open, run args
      sessions.py    # run supervisor: pty, pid-file, signals, streams, history
      phone.py       # content providers: messages, calls, contacts, calendar
      mirror.py      # scrcpy-server proxy (video/audio/control)
      doctor.py      # environment checks + guided tool installs
      auth.py        # single-owner credential + sessions
    server/
      app.py         # FastAPI app factory, lifespan, static mount
      routes/        # system.py, devices.py, projects.py, runs.py, settings.py, auth.py
      ws.py          # /ws/events, /ws/runs/{id}
      security.py    # auth middleware, CSRF, token, bind/reach rules
    cli/
      main.py        # argparse + dispatch (ported)
      tui/           # the terminal dashboard (ported)
  web/               # React + TS + Vite SPA (own package.json)
  tests/
  packaging/
    install.sh
    fenox.service
    Dockerfile
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

- The hub runs the **unmodified scrcpy-server** matching the installed scrcpy,
  pushed to the device and started over adb — no forked protocol.
- The hub sets up `adb forward`, opens the video/audio/control sockets, and
  **proxies bytes over WebSocket** (Python asyncio). It never decodes video.
- The browser parses with **`@yume-chan/scrcpy`** and renders via **WebCodecs**
  (`scrcpy-decoder-webcodecs`). Control events travel back over the same socket.
- scrcpy-server version is pinned and verified at connect time.
- **Note:** the dev machine currently has **scrcpy 1.25**; audio forwarding needs
  scrcpy ≥ 2.0. Phase 5 either upgrades scrcpy or ships video+control first.

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
Zustand for UI state, **xterm.js** for the run terminal and logcat,
**`@yume-chan/scrcpy`** for mirroring.

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
- Distribution: **curl installer + systemd --user + Docker**, PWA later.
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
