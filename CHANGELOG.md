# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
- Contributor documentation: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, `CHANGELOG.md`, plus issue and pull request templates.

### Changed

- **The interactive dashboard is now actually live and single-keypress.** It
  previously read as a live dashboard but required **Enter** for every choice and
  only redrew after an action returned. It now responds to a single keypress and
  refreshes itself every few seconds while waiting, using a portable raw-key
  layer (`termios`/`tty` on POSIX, `msvcrt` on Windows) that degrades to a
  validated line prompt when stdin is not a terminal.
- **Per-device navigation is grouped instead of a wall of keys.** `device_actions`
  presented 30+ single-letter commands (`A`–`Z`, `0`, `#`, `@`, `~`) at once. It
  is now a Command Center offering six named categories, with the full keypad
  still available as an explicit expert mode (`e`) so nothing was lost.
- Every menu now accepts a single keypress to continue instead of demanding
  Enter, unknown keys are ignored rather than printing an error, and four
  category menus that were previously unreachable dead code are now the actual
  navigation.
- **Platform support is now stated honestly: Linux and WSL.** The README and
  badge no longer claim Windows. A native Windows client needs a real GUI and is
  planned as a separate application rather than a port of this terminal tool;
  the CLI's device layer is POSIX-only today (it shells out to `timeout`, `tmux`
  and `/dev/null` redirection), so shipping a Windows binary would have installed
  something that could not talk to a device.
- **A fresh install starts empty.** First run used to write a sample config
  containing a fictional `myapp`, a `myphone` and an `emulator`, so every new
  user got aliases such as `myapp-myphone` pointing at projects and devices that
  did not exist on their machine.
- The projects directory is no longer hardcoded to `~/Projects`; it comes from
  your configuration and falls back to the first conventional location that
  actually exists.
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
- **Version comparison in `fenox update`** treated versions as strings, so
  `1.9.0` looked newer than `1.10.0` and the updater would rebuild from an
  outdated local checkout instead of downloading the newer release.
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
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.sh | bash
```

[Unreleased]: https://github.com/onefennox/fenox-mobile/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/onefennox/fenox-mobile/releases/tag/v1.0.0
