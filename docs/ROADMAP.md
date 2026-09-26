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
| M5 | Access: LAN/tunnel/TLS/PWA | **code complete, verification pending** |
| M6 | Onboarding and guided installs | **code complete, verification pending** |

---

## M0 — Foundation ✅

- [x] Repository, packaging, lint/type/test gates, CI
- [x] `core`: `db` (SQLite + migrations), `config` (XDG + legacy import), `auth`, `host`
- [x] `server`: app factory, owner auth (setup/login/logout/token), `/api/system`
- [x] `cli`: `serve`, `auth reset`, `info`
- [x] Installer (curl, `uv`/`pipx`, `--user` or `--system`), systemd user unit

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

### M6d — Works on whatever machine it lands on

**Outcome:** a host that already has adb and Flutter set up should need no
arguments, no environment variables and no manual path entry.

- [x] Host path resolution is platform-correct: both `adb` and `adb.exe`, both
      `flutter` and `flutter.bat`, the Windows SDK under `LOCALAPPDATA`, and the
      Homebrew prefixes on Intel and Apple Silicon. A Mac with only
      `brew install android-platform-tools` used to look like it had no adb.
- [x] `adb.conflicting_installations` — several adb binaries whose versions
      disagree take the device from each other, which looks like a flaky cable.
- [x] The installer offers to put the launcher on `PATH` rather than printing a
      line the user has to interpret.
- [x] `install.sh --system` for a machine-wide FHS install, and it refuses to run
      unprivileged instead of failing halfway.
- [x] A missing Python produces the commands that fix it, per distro.
- [x] The installer reads the JSON report rather than scraping the printed one,
      so reformatting the report cannot silently break it.
- [ ] A Homebrew formula. It needs a tagged release to hash, so it cannot exist
      before the first tag — tracked rather than shipped broken.

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
- [x] Files: browse, download, push, pull, upload, mkdir, delete
      (`core/files.py`, `/api/devices/{id}/files*`, `tests/test_files.py`).
- [x] Control: reboot, Wi-Fi/data/Bluetooth, volume, brightness, shell.
- [x] Logs: logcat stream over WebSocket.
- [x] Dev tools: device info, battery, storage, processes, notifications.
- [x] Phone data: messages, calls, contacts, calendar (core/phone.py + routes + screens).

### Exit criteria

- [ ] Every action available in today's CLI is available in the browser with no terminal.

> Code is complete, including the file manager, and covered by tests. The exit
> criterion is verified manually against a physical phone.

---

## M4 — In-browser mirroring

**Outcome:** see and control the phone screen in the browser.

- [x] `core/mirror.py`: push and start the pinned scrcpy server, `adb reverse` the
      socket, read raw Annex-B H.264 from the device.
- [x] `ffmpeg` remux to fragmented MP4; fragments emitted on a timer, not only at
      keyframes, so latency does not depend on keyframe frequency.
- [x] Stream the fMP4 over the existing app WebSocket; the hub never decodes or
      transcodes video.
- [x] Frontend: Media Source Extensions into a native `<video>`; tap, swipe and
      key input via the toolbox action paths.
- [x] Version and dependency check surfaced as `/mirror/status`.
- [ ] Audio (needs scrcpy ≥ 2.0; the installed server here is 1.25).

### Exit criteria

- [ ] Usable latency; touch and keyboard drive the phone.

> **Note (design change).** The original plan was `@yume-chan/scrcpy` +
> WebCodecs over a raw H.264 WebSocket proxy. An intermediate WebRTC/MediaMTX
> design was also built and then abandoned. The shipped design is the fMP4 + MSE
> pipeline documented in SPEC §10a — no WebCodecs, no extra ports, no
> negotiation. `@yume-chan/scrcpy` is deliberately **not** a dependency; input
> reuses the toolbox paths so one code path drives the device either way.
>
> The pipeline builds clean but is protocol- and version-sensitive, so it stays
> unverified until run against a physical phone.

---

## M5 — Access

**Outcome:** reach the hub from another machine or a phone, safely.

- [x] Settings-driven reach: localhost → LAN → remote, with an explicit note that
      a bind change needs a restart, and the URLs that become reachable.
- [x] TLS support (flag or `FENOX_TLS_CERT`/`FENOX_TLS_KEY`) for anything off
      localhost; the owner session and token are enforced in every tier.
- [x] Access token shown and rotatable from Settings.
- [x] PWA: manifest, service worker for the app shell, installable on localhost.
- [x] `fenox service install|uninstall` and `fenox update`.

---

## M6 — Onboarding

**Outcome:** a fresh machine reaches "running app" with minimal terminal use.

- [x] Detect adb, scrcpy, Flutter, tmux, ffmpeg, git, node, qrencode, zbarimg,
      with versions and whether each is required.
- [x] Guided installs: tools needing root return the exact command and are never
      run by the hub; large SDKs link to their official guide.
- [x] WSL/Windows guidance when Windows adb is missing.
- [x] System page in the web app showing all of the above.

### M6b — Connections that explain themselves

**Outcome:** nobody has to run a command to get a phone working, and when
something *is* in the way, the app says which thing and what to do.

- [x] `core/usbipd.py` — the WSL USB/IP bridge: discovery, output parsing, attach,
      and the command builders for the steps that need administrator rights.
- [x] `core/connect.py` — `diagnose()` returns findings (`what` / `why` / `fix` /
      `auto` / `runs_in`), not a bare "0 devices". Read-only by construction.
- [x] `repair_usbipd()` — Fenox performs every `attach` itself, on a timer, with a
      cooldown. Reboots and unplug/replug are uneventful because usbipd
      attachments are not persistent and no third-party tool automates it.
- [x] Findings surfaced on the Connect page with copy-to-clipboard, plus
      **Let Fenox fix this** for the ones that need no rights.
- [x] A phone publishing `_adb-tls-pairing` is discovered, so the IP and port are
      never typed — only the six-digit code.
- [x] Wireless is the default tab; USB states plainly that on WSL it needs a bridge.
- [x] adb release detection: on Platform Tools 37+ (ADB Wi-Fi 2.0) a paired phone
      reconnects on its own, and Fenox says an upgrade would remove work.
- [x] `core/log.py` — the hub logs every connection decision and repair, so
      `fenox serve` explains what it saw and what it did. The watcher no longer
      swallows its exceptions silently.
- [x] An unfixable failure is logged once, not on every poll.

### M6c — A diagnosis you can trust, and share

**Outcome:** one command that tells the truth about any machine, and a report
someone can paste into a bug tracker without leaking their identity.

- [x] `core/env.py` — one owner for every environment fact, cached. Replaces two
      divergent adb version parsers that made the product contradict itself
      (`1.0.41` from the doctor, `36.0.0` from the connection layer).
- [x] `core/report.py` — the report as data plus a renderer, so terminal, `--json`
      and a future web view are one answer rendered three ways, and are testable.
- [x] `fenox doctor` rebuilt: verdict that cannot contradict its own body, fixes
      that say *where* to run them, prose not rendered as commands.
- [x] Redaction by default (home, Windows account, serials, IP addresses);
      `--full` to opt out. Secrets are never included.
- [x] Exit code non-zero only for blocking problems, so advice never reads as a
      broken machine and the command is usable from a script.
- [x] `device.stale_adb_entry` — names the "adb lists a device the bridge has not
      attached" state, and warns against the `adb kill-server` reflex that
      disconnects everything and takes the USB attachment with it.
- [x] `adb.missing` / `adb.too_old` findings, so the engine is problem-keyed and
      not tied to one host.
- [x] **Verify after fix.** `connect.verify()` re-diagnoses after every action and
      reports one of four outcomes — `resolved`, `escalated`, `unchanged`,
      `blocked`. `escalated` exists because an action that fails can still reveal
      the real blocker, and calling that "fixed" is a lie. `fenox doctor --fix`
      and `POST /api/system/connection/repair` both use it; the dashboard shows the
      outcome and the next step.
- [x] `fix_all()` runs automatic fixes **one at a time**, verifying each, because
      acting on a stale list is how a tool makes a machine worse while helping.
- [x] Fast and deep passes. `diagnose(deep=False)` runs on every dashboard poll;
      `deep=True` adds the slow checks and is what `fenox doctor` uses.
- [x] Linux **udev** check: a device on the bus that this user cannot open is
      reported as a permissions problem, because otherwise it is
      indistinguishable from a missing cable.
- [x] **Android SDK licences** and `cmdline-tools` checks, parsed from
      `flutter doctor -v`. A build failing on a licence message that never says
      "licence" is otherwise very hard to recognise.

### Exit criteria

- [ ] On WSL, plugging a phone in and running nothing results in a connected device.
- [ ] After a reboot or an unplug/replug, the phone comes back with no action.
- [ ] A phone held by a stale export produces one clear instruction, not two.
- [ ] On a machine with adb and Flutter fully set up and one phone connected,
      `fenox doctor` prints "no problems found" and exits 0.
- [ ] On a fresh machine with nothing installed, `fenox doctor` names every
      missing piece with an installable fix and exits 1.
- [ ] The report pasted into a public issue leaks no home path, account name,
      serial or address.
- [ ] `fenox doctor --fix` moves a healthy-but-recoverable machine to healthy, and
      says `narrowed` rather than `fixed` when it cannot finish.

> CI now runs the suite on Linux, macOS and Windows, and includes a job that
> asserts `fenox doctor` **fails** on a runner with nothing installed — the
> regression where a broken machine reported every tool as `ok` is now guarded in
> CI rather than only by a code review. Those matrix jobs are unverified until
> pushed: only the Linux job has run.

> The code is covered by tests (`tests/test_connect.py`, 37 cases) but every exit
> criterion needs a real phone and a real WSL reboot, which is exactly the
> verification M1–M4 are still waiting on.

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
