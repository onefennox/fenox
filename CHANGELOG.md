# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] — 2026-09-18

### Changed

- **The project is called Fenox.** The installed command is `fenox` (the old
  second-name alias is gone), the source is `src/fenox.py`, release assets are
  `fenox-linux-<arch>`, and the repository is `onefennox/fenox`.
- **The device screen shows the whole toolset at once.** The six category
  sub-menus and the separate expert keypad are gone: all ~45 per-device actions
  are on one screen, grouped under their headings and numbered straight through,
  so any of them is a typed number away rather than two menus deep.
- **Numbered screens take typed input.** Keystrokes collect on an input line
  instead of firing immediately, which is what makes numbers past 9 usable (`12`
  would otherwise open `1` on the way). The line shows what was typed and turns
  red when it names nothing; `Backspace` edits, and `Esc` clears it before it
  goes back. Arrow keys still move the highlight and Enter still opens it.

### Added

- **`fenox phone messages` — read your messages from the terminal.** Threads with
  unread counts, one conversation oldest-first, a body search, marking a thread
  read on the phone, and `--json` for scripting. Contact names are resolved onto
  numbers using the phone's own contacts, and `--redact` hides numbers and bodies
  for screen sharing. It reads through Android's content providers, so it needs no
  root and nothing installed on the phone; a ROM that refuses access says so
  instead of showing an empty inbox. The dashboard's device screen has a
  **Read messages** row that opens the same thing as a browsable screen.
- **`fenox phone calls` — read your call log from the terminal.** Recent calls
  newest first, `--missed`/`--incoming`/`--outgoing`, a per-number history with
  `--from`, `--days` to widen the window (0 is the whole log), `--search` by
  number or contact name, `--mark-read` to clear the "new call" flags, `--json`,
  and `--redact`. Contact names are resolved from the phone's own contacts; a call
  that never connected shows `—` rather than a misleading `0s`; and a withheld
  number reads as unknown instead of as the provider's `NULL` placeholder. Like
  messages it needs no root and nothing installed on the phone. The dashboard's
  device screen has a **Read the call log** row that opens it as a screen with a
  missed-only toggle, search, and a per-call detail view.
- **`fenox phone contacts` — the phone's address book in the terminal.** Search
  by name or number, `--json`, `--redact`, and a TSV export. The device screen's
  **Read contacts** row opens it as a browsable screen where a contact leads to
  calling them, opening the dialler, messaging them, or their calls and messages.
- **`fenox phone calendar` — the phone's calendar in the terminal.** Upcoming
  occurrences from the *instances* table, so recurring events appear every time
  they occur rather than once at their original date; `--days`, `--search`, a
  per-calendar filter, `--json`, `--redact`, and `--add "Title" --at 09:30` (or
  `YYYY-MM-DD HH:MM`) to put an event on the phone. The device screen's **Read
  the calendar** row opens the same as a screen with add, widen and search.
- **One-time setup in `fenox init`:** asks where your Flutter projects live,
  validates the path, offers to create it, and records it in `~/.fenox.json` so
  it never has to be guessed again. Also captures an optional remote API domain
  used to derive production URLs. Re-runnable with `fenox init --reset-settings`,
  and safe to run without a terminal (it skips the questions rather than hanging).
- **`fenox uninstall`** with `--yes` and `--keep-config`: removes the binary, the
  `fenox` symlink, config, backups and run history, and strips only its own hooks
  from `~/.bashrc` and `~/.zshrc`. Running it from a source checkout never
  deletes the checkout.
- **End-to-end release test** (`tests/test_release_e2e.sh`): stages a real release
  layout, serves it over loopback HTTP and exercises the one-liner install, the
  repo-clone install, the per-asset checksum fallback and refusal of a tampered
  download. It now gates publishing in the release workflow.
- **A proper session opening and sign-off.** Launching `fenox` now prints a
  titled boot screen — version, platform and Python, the environment banner, and
  a checklist of the config file, the adb server, your projects directory and the
  shell hooks — with a spinner while the shared adb server comes up. Quitting
  prints a matching sign-off with the session duration, what was deployed, and
  the most useful next step. Both screens are drawn once per session and appear
  on every exit path.
- **A rotating tip on the opening screen.** One tip per day, picked only from
  the ones that apply to this machine — first device, no apps yet, disabled
  devices, several devices — so it never tells someone with four phones to go
  and find their first one.
- Empty-state hints on the dashboard: with no devices or apps it now says which
  entry discovers or registers one, instead of showing bare tables.
- **The dashboard shows less and says more.** Devices and apps used to be listed
  twice — once in a status table and again in the action list — so the screen ran
  long and the same name appeared in two places. The tables are gone: each device
  and app is one row carrying its own status (model, online/offline, battery,
  screen, foreground app; git branch, last deploy), and the maintenance actions
  follow in the same list. The separate online/offline counter line is gone too,
  since every row now states its own state.
- `tests/test_menu_wiring.py`: presses every key on every dashboard menu and
  asserts it runs the action that menu advertises.
- `tests/test_session_ui.py`: drives the real CLI over a pseudo-terminal and
  asserts the boot screen, the sign-off, single-keypress quitting, Ctrl+C, the
  end-of-input path and that shell helpers never wait on adb.
- Contributor documentation: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, `CHANGELOG.md`, plus issue and pull request templates.

### Changed

- **The interactive dashboard is now actually live.** It previously read as a
  live dashboard but only redrew after an action returned. It now refreshes
  itself every few seconds while waiting for your choice, reading keys as they
  are pressed through a raw-key layer built on `termios`/`tty` that degrades to a
  validated line prompt when stdin is not a terminal.
- **Per-device navigation is grouped instead of a wall of keys.** `device_actions`
  presented 30+ single-letter commands (`A`–`Z`, `0`, `#`, `@`, `~`) at once. It
  is now a Command Center offering six named categories, with the full keypad
  still available as an explicit expert mode (`e`) so nothing was lost.
- Every menu acts on a key as soon as it is pressed, unknown keys are ignored
  rather than printing an error, and four category menus that were previously
  unreachable dead code are now the actual navigation.
- **Platform support is now stated honestly: Linux and WSL.** The README and
  badge no longer claim Windows. A native Windows client needs a real GUI and is
  planned as a separate application rather than a port of this terminal tool;
  the CLI's device layer is POSIX-only today (it shells out to `timeout`, `tmux`
  and `/dev/null` redirection), so shipping a Windows binary would have installed
  something that could not talk to a device.
- **The last native-Windows remnants are gone from the code.** With support
  stated as Linux and WSL, the unreachable Windows path was only dead weight and
  a source of confused docs: the `msvcrt` key reader, the `IS_WINDOWS` branches
  in `fenox init` and the platform label, and the `winget` install hints are
  removed. Everything that touches Windows *from WSL* — the shared `adb.exe`
  server on port 5038, the Desktop output folder, the PowerShell clipboard calls
  — is unchanged, because that is the WSL support working as designed. The
  README, `CONTRIBUTING.md`, `SECURITY.md`, the issue templates and the
  installer's refusal message now all say the same thing: Linux and WSL, and on
  Windows run fenox inside WSL.
- **A fresh install starts empty.** First run used to write a sample config
  containing a fictional `myapp`, a `myphone` and an `emulator`, so every new
  user got aliases such as `myapp-myphone` pointing at projects and devices that
  did not exist on their machine.
- The projects directory is no longer hardcoded to `~/Projects`; it comes from
  your configuration and falls back to the first conventional location that
  actually exists.
- **Ctrl+C always quits.** It used to be swallowed by whichever menu was open
  (on the dashboard it was treated as "go back" and exited 0). It now unwinds to
  the sign-off and exits 130, from any menu, including the `_wait_any_key` pause
  after an action.
- **Every screen is now a selection list: `↑`/`↓` to move, **Enter** to confirm.**
  A row is highlighted with a cursor instead of everything being a bare shortcut:
  pressing a row's own key moves the highlight to it, and Enter is what runs it,
  so a stray keypress can no longer fire a destructive action. Device and app
  rows sit above the maintenance shortcuts in the same list, and the cursor is
  remembered when you come back to a screen.
- **Every dashboard menu uses the same renderer.** The six per-device categories
  and the app menu each printed their own header and read a key by hand; they now
  share the dashboard's breadcrumb (`dashboard › device › screen & input`), a
  subtitle naming the device or app they act on, the same key legend, and
  `b`/`Esc` to go back. They also no longer wipe the screen, so the opening screen
  and your scrollback survive.
- The expert keypad reads keys as they are pressed instead of demanding Enter
  after every command.
- The live dashboard refreshes itself twice a second instead of four times, which
  keeps the terminal quiet without any visible difference.
- Release builds publish the per-asset `.sha256` files alongside `SHA256SUMS`, so
  either checksum source resolves.
- `README.md` documents requirements, both installers, uninstall, troubleshooting
  and an FAQ, and no longer advertises macOS.

### Fixed

- **Checksums are now actually verified on install.** `install.sh` declared
  `local tag="$1" ... base="...$tag"` in a single statement, and bash expands
  every word of such a statement before assigning any of them, so `$tag` was
  unset and `set -u` aborted the checksum lookup on every call. The one-liner
  install could never verify a download and refused with a misleading
  "no checksum file" message.
- **Screen mirroring failed silently on new Android.** `action_mirror` sent
  scrcpy's output to /dev/null, so on an Android 15 phone (where scrcpy 1.x —
  still the version Ubuntu 24.04 packages — has its screen encoder break on
  removed platform calls) choosing *Mirror* did nothing at all: no window, no
  error, nothing. It now warns up front when the installed scrcpy is below the
  version floor the device's Android needs, with copy-paste install steps; keeps
  the window's output in a timestamped log next to the screenshots; and reports
  when the mirror did not come up, with the log's last lines.
- **First run was a dead end.** With nothing configured yet, the empty-state
  dashboard stopped on a "press Enter to open the dashboard" pause before its own
  loop even started. That pause only accepted Enter or Escape, so the obvious
  keys — `x` to quit, or `d` for Doctor as the panel itself suggests — were
  swallowed and the session appeared frozen. The guidance is the dashboard's
  empty state, so there is no pause: the dashboard is live immediately.
- **Enter was a dead key.** The key reader reported it, but no screen handled it,
  so pressing Enter anywhere did nothing at all. It now confirms the highlighted
  row, which is the primary way to choose anything.
- **An arrow key could quit the dashboard.** Escape sequences were read through
  Python's buffered stdin, so the rest of `↑`/`↓` could already be sitting in the
  buffer: the sequence looked empty and was reported as Escape. Keys are now read
  from the file descriptor, and an unrecognised sequence is ignored instead of
  being treated as Escape.
- **The dashboard's "press a device # or app #" did nothing.** `run_menu` only
  accepted the keys it was drawing, so every number was treated as an unknown key
  and silently ignored — the one-line hint on the opening screen advertised a
  shortcut that could not work.
- **`b` meant both "back" and "Read clipboard"** on the Screen & input menu, and
  back won, so Read clipboard was unreachable. The letter shortcuts there are now
  `a` (copy text to device), `v` (read clipboard), `u` (open URL) and `o` (open
  last capture).
- **In the expert keypad, Edit / Toggle / Remove / Refresh could never run.** The
  upper-case action map matched `e` (List apps), `g` (Clear app data), `h` (Force
  stop) and `d` (Open app) first. Config keys are now resolved before the action
  map, so all four work.
- **Version comparison in `fenox update`** treated versions as strings, so
  `1.9.0` looked newer than `1.10.0` and the updater would rebuild from an
  outdated local checkout instead of downloading the newer release.
- **A child process could swallow the keypress you just typed.** Under WSL the
  `cmd.exe`, `taskkill.exe` and `powershell.exe` interop calls inherited the
  terminal's stdin, so a newline-less keypress could be consumed before the menu
  ever saw it — and any piped input was eaten before the first prompt. Every
  captured, non-interactive command now runs with stdin on `/dev/null`.
- **`--version`, `--help` and `--generate-completions` no longer start an adb
  server.** They ran the full startup path, so a version query could spawn a
  server on a port — and the completion helper runs on every new shell.
- `fenox build` refuses to produce a release APK when no remote API URL is
  configured, rather than embedding an empty or placeholder URL.
- Remote launches without a configured remote domain fall back to the local API
  URL and say so, instead of embedding a placeholder `example.com` URL.
- macOS is no longer advertised. The installer downloaded Linux binaries on
  macOS; it now refuses with a clear message instead of installing a binary that
  cannot run.

### Security

- Installer and self-updater verify SHA-256 against `SHA256SUMS` or a per-asset
  `.sha256` file, match the asset name exactly, and refuse to install when no
  checksum is published or the digest does not match.

## [1.0.0] — 2026-09-18

First stable release: one command to connect, monitor and launch Flutter apps on
every device you own, wrapping ADB connections, reverse-port binding, log
streaming, screen mirroring, media capture and Flutter launches into instant
terminal aliases.

Install:

```bash
# Linux / WSL
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/install.sh | bash
```

[Unreleased]: https://github.com/onefennox/fenox/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/onefennox/fenox/releases/tag/v1.0.1
[1.0.0]: https://github.com/onefennox/fenox/releases/tag/v1.0.0
