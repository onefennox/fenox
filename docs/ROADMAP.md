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
| M1 | Devices in the browser | **code complete, device verification pending** |
| M2 | Projects, run + hot reload | **code complete, device verification pending** |
| M3 | Device toolbox + phone data parity | **code complete, verification pending** |
| M4 | In-browser mirroring | **code complete, device verification pending** |
| M5 | Access: LAN/tunnel/TLS/PWA | **next** |
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

- [x] `core/adb.py` — port: shared server, device enumeration, pending states,
      connect, pair, mDNS candidates, reverse ports, shell.
- [x] `core/devices.py` — port: registry, telemetry, `autodetect`, wireless
      autodetect, `DeviceWatcher`; persist through `Store`.
- [x] Routes:
  - [x] `GET /api/devices`, `POST /api/devices/discover`, `POST /api/devices/pair`
  - [x] `POST /api/devices/{id}/connect`
  - [x] `PATCH /api/devices/{id}`, `DELETE /api/devices/{id}`
  - [x] `GET /api/devices/{id}/telemetry`, `GET /api/devices/{id}/screenshot`
- [x] `WS /ws/events` — live device state.
- [x] Tests against a fake adb (no device required).

### Frontend (`web/`)

- [x] Scaffold Vite + React + TS + Tailwind + TanStack Query; build into `src/fenox/web`.
- [x] App shell, router, auth guard; Setup and Login screens.
- [x] Devices page: list with live status, connect, pair, rename, enable/disable, remove.
- [x] Device detail shell with telemetry and screen preview (filled out in M3).

### Exit criteria

- [ ] A USB phone and a wireless phone both appear automatically within one refresh.
- [ ] Renaming, disabling, and removing persist and reflect in the CLI too.
- [ ] Disconnecting a phone marks it offline live; reconnecting restores it.

> The code is complete; the exit criteria require a physical phone and are
> verified manually before M1 is marked done.

---

## M2 — Projects, run + hot reload (the core feature)

**Outcome:** register a Flutter project, run it on a device from the browser,
watch the terminal, hot reload / restart / stop, open DevTools.

### Backend

- [x] `core/projects.py` — CRUD, scan, port/backend/URL/package detection.
- [x] `core/flutter.py` — binary resolution, run/build argv.
- [x] `core/sessions.py` — supervisor:
  - [x] spawn `flutter run` under a pty with `--pid-file`
  - [x] poll pid-file, parse VM Service + DevTools URLs
  - [x] `SIGUSR1` reload, `SIGUSR2` restart, `SIGINT`/`SIGTERM` stop
  - [x] transcript buffer + subscriber fan-out
  - [x] orphan detection on boot
- [x] Routes: `/api/projects*`, `/api/runs*`, `/api/runs/batch`, `WS /ws/runs/{id}`.
- [x] Tests using a fake `flutter` binary that installs signal handlers.

### Frontend

- [x] Projects list, add, scan, edit (port, local/remote API and socket URLs).
- [x] Run page: live xterm.js terminal, Reload / Restart / Stop, DevTools link, status.
- [x] Runs page: active-run grid with live terminals, plus history.

### Exit criteria

- [ ] Run a real Flutter app from the browser and hot-reload it.
- [ ] Stop leaves no orphan process; history records the run.

> The code is complete and covered by an automated fake-flutter test; the exit
> criteria are verified against a real Flutter SDK and phone before M2 is done.

---

## M3 — Device toolbox + phone data

**Outcome:** parity with the current CLI device screen, in the browser.

- [x] Screen: screenshot, record, wake, lock, type, tap, swipe, key events, clipboard, open URL.
- [x] Apps: list, install APK, uninstall, clear data, force stop, info, open.
- [ ] Files: browse, push, pull.
- [x] Control: reboot, Wi-Fi/data/Bluetooth, volume, brightness, shell.
- [x] Logs: logcat stream over WebSocket.
- [x] Dev tools: device info, battery, storage, processes, notifications.
- [x] Phone data: messages, calls, contacts, calendar (core/phone.py + routes + screens).

### Exit criteria

- [ ] Every action available in today's CLI is available in the browser with no terminal.

> File browsing is the one remaining gap; it lands next with push and pull.

---

## M4 — In-browser mirroring

**Outcome:** see and control the phone screen in the browser.

- [x] `core/mirror.py`: push and start the installed scrcpy server, `adb forward`,
      read the video socket (device name, codec metadata, length-delimited frames).
- [x] WebSocket video proxy; the hub never decodes video.
- [x] Frontend: WebCodecs decode to a canvas; tap, swipe, and key controls.
- [x] Version and dependency check surfaced as `/mirror/status`.
- [ ] Audio (needs scrcpy ≥ 2.0; the installed server here is 1.25).
- [ ] `@yume-chan/scrcpy` client (not used; the minimal 1.x framing is read directly
      and input goes through the toolbox actions).

### Exit criteria

- [ ] Usable latency; touch and keyboard drive the phone.

> The video proxy and decoder are implemented and build clean, but the protocol
> is version-sensitive and unverified without a device. The hub requests
> `send_frame_meta` and no control channel; input uses the toolbox paths, so one
> code path drives the device whether mirroring or not.

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
