# Fenox — development roadmap

Companion to [`SPEC.md`](SPEC.md). This is the execution plan: what gets built,
in what order, and how we know it is done. Optimised for **speed without
rewrites** — every phase ships something usable, and the hard device engine is
ported, not reinvented.

## Principles

1. **Vertical slices.** Each milestone produces a working feature in the browser,
   not a layer with no UI.
2. **Port, don't rewrite.** `adb`, `devices`, `phone`, and the Flutter/pty logic
   come from `fenox-mobile/src/fenox.py` into `core/`, adapted to `Store`.
3. **API first, then UI.** The server exposes a clean route; the web app consumes it.
4. **No speculative abstraction.** Add structure when a second caller needs it.
5. **Definition of done:** `ruff` + `mypy` + `pytest` green, feature usable end to end.
6. **Always shippable.** The CLI and hub keep working throughout.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| M0 | Foundation: repo, core skeleton, hub, owner auth, SQLite, packaging | **done** |
| M1 | Devices in the browser | **next** |
| M2 | Projects, run + hot reload | planned |
| M3 | Device toolbox + phone data parity | planned |
| M4 | In-browser mirroring | planned |
| M5 | Access: LAN/tunnel/TLS/PWA | planned |
| M6 | Onboarding and guided installs | planned |

---

## M0 — Foundation ✅

- [x] Repository, packaging, lint/type/test gates, CI
- [x] `core`: `db` (SQLite + migrations), `config` (XDG + legacy import), `auth`, `host`
- [x] `server`: app factory, owner auth (setup/login/logout/token), `/api/system`
- [x] `cli`: `serve`, `auth reset`, `info`
- [x] Installer, systemd user unit, Dockerfile

---

## M1 — Devices

**Outcome:** connect a phone over USB and over wireless, see it in the browser,
rename it, watch it come and go live.

### Backend

- [ ] `core/adb.py` — port: shared server, device enumeration, pending states,
      connect, pair (code + QR), mDNS candidates, reverse ports, shell.
- [ ] `core/devices.py` — port: registry, telemetry, `autodetect`, wireless
      autodetect, `DeviceWatcher`, health; persist through `Store`.
- [ ] Routes:
  - [ ] `GET /api/devices`, `POST /api/devices/discover`
  - [ ] `POST /api/devices/{id}/connect`, `POST /api/devices/{id}/pair`
  - [ ] `PATCH /api/devices/{id}`, `DELETE /api/devices/{id}`
  - [ ] `GET /api/devices/{id}/telemetry`, `GET /api/devices/{id}/screenshot`
- [ ] `WS /ws/events` — device added/removed/state changes + telemetry ticks.
- [ ] Tests against a fake adb (no device required).

### Frontend (`web/`)

- [ ] Scaffold Vite + React + TS + Tailwind + TanStack Query; build into `src/fenox/web`.
- [ ] App shell, router, auth guard; Setup and Login screens.
- [ ] Devices page: list with live status, connect, pair, rename, enable/disable, remove.
- [ ] Device detail shell (empty sections to be filled in M3).

### Exit criteria

- [ ] A USB phone and a wireless phone both appear automatically within one refresh.
- [ ] Renaming, disabling, and removing persist and reflect in the CLI too.
- [ ] Disconnecting a phone marks it offline live; reconnecting restores it.

---

## M2 — Projects, run + hot reload (the core feature)

**Outcome:** register a Flutter project, run it on a device from the browser,
watch the terminal, hot reload / restart / stop, open DevTools.

### Backend

- [ ] `core/projects.py` — port: CRUD, scan, port/backend/URL/package detection, groups.
- [ ] `core/flutter.py` — port: binary resolution, build, install, open, run argv.
- [ ] `core/sessions.py` — **new** supervisor:
  - [ ] spawn `flutter run` under a pty with `--pid-file`
  - [ ] poll pid-file, parse VM Service + DevTools URLs
  - [ ] `SIGUSR1` reload, `SIGUSR2` restart, `SIGINT`/`SIGTERM` stop
  - [ ] ring buffer + subscriber fan-out; multi-device sessions
  - [ ] orphan detection on boot
- [ ] Routes: `/api/projects*`, `/api/runs*`, `WS /ws/runs/{id}`, `/ws/events`.
- [ ] Tests using a fake `flutter` binary that installs signal handlers.

### Frontend

- [ ] Projects list, add/scan, edit (path, backend URLs, ports).
- [ ] Run page: live xterm.js terminal, Reload / Restart / Stop, DevTools link, status.
- [ ] Multi-device run grid.

### Exit criteria

- [ ] Run a real Flutter app from the browser and hot-reload it.
- [ ] Stop leaves no orphan process; history records the run.

---

## M3 — Device toolbox + phone data

**Outcome:** parity with the current CLI device screen, in the browser.

- [ ] Screen: mirror launcher (M4), screenshot, record, wake, lock, type, tap, swipe, key combos, clipboard.
- [ ] Apps: list, install APK, uninstall, clear data, force stop, info, open.
- [ ] Files: browse, push, pull.
- [ ] Control: reboot, Wi-Fi/data/Bluetooth, volume, brightness, shell.
- [ ] Logs: logcat stream over WebSocket.
- [ ] Dev tools: device info, battery, network, storage, processes, notifications.
- [ ] Phone data: messages, calls, contacts, calendar (port `core/phone.py` + routes + screens).

### Exit criteria

- [ ] Every action available in today's CLI is available in the browser with no terminal.

---

## M4 — In-browser mirroring

**Outcome:** see and control the phone screen in the browser.

- [ ] `core/mirror.py`: push/start pinned scrcpy-server, `adb forward`, open sockets.
- [ ] WebSocket byte-proxy (asyncio), no video decoding on the hub.
- [ ] Frontend: `@yume-chan/scrcpy` + WebCodecs; touch, keyboard, clipboard.
- [ ] Version pinning and compatibility check.

### Exit criteria

- [ ] Usable latency; touch and keyboard drive the phone.

---

## M5 — Access

**Outcome:** reach the hub from another machine or a phone, safely.

- [ ] Settings-driven reach: localhost → LAN → remote tunnel.
- [ ] TLS for anything off localhost; token + session enforced.
- [ ] PWA install.
- [ ] systemd service polish and update command.

---

## M6 — Onboarding

**Outcome:** a fresh machine reaches "running app" with minimal terminal use.

- [ ] Detect adb, platform-tools, scrcpy, Flutter, tmux; report versions.
- [ ] Guided installs: no-sudo tools automated, sudo tools shown with the exact command.
- [ ] WSL/Windows-side guidance for USB.

---

## Order of attack (fast path)

1. **M1 backend** — port `adb` + `devices`, add routes and events. *(days)*
2. **M1 web scaffold + Devices UI** — first real screens.
3. **M2 backend** — `sessions` supervisor, projects, runs. *(the risk; do it early)*
4. **M2 web** — live terminal and hot reload.
5. **M3** — toolbox and phone-data screens.
6. **M4** — mirroring. 7. **M5** — access. 8. **M6** — onboarding.

## Cross-cutting (maintained every phase)

- Structured logging, consistent error responses, no stack traces over HTTP.
- Coverage floor raising per phase; `ruff`, `mypy`, `pytest` in CI.
- Keep the CLI a working management surface.
- Update `docs/` whenever a decision changes.
