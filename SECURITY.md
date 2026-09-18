# Security Policy

## Supported versions

The latest release is supported. Older releases do not receive security fixes —
run `fenox update` (or re-run the installer) to get current.

| Version | Supported |
|---|---|
| 1.x (latest release) | ✅ |
| older | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting on this repository:
**Security → Report a vulnerability** (or go straight to
<https://github.com/onefennox/fenox-mobile/security/advisories/new>).

That opens a private advisory visible only to the maintainers. Please include:

- what the issue is and the impact you believe it has,
- the version (`fenox --version`) and platform,
- step-by-step reproduction, ideally with a minimal example,
- any proof-of-concept you have.

You will get an acknowledgement, and we will keep you updated on the fix. Please
give us a reasonable window to release a fix before disclosing publicly — we are
happy to credit you in the advisory and the changelog.

## What is in scope

Fenox installs a binary onto your machine and can replace itself, so the
following are treated as security-relevant:

- **Supply chain of the release artifacts.** The installer and `fenox update`
  verify a published SHA-256 before writing anything. Anything that would let a
  download be installed *without* a verified checksum, or that makes the hash
  comparison bypassable (for example accepting an unanchored or truncated
  digest), is in scope.
- **The self-update path.** `fenox update` replaces the running binary atomically
  after verification. Path handling, symlink behaviour and file permissions
  there are in scope.
- **Command injection.** Fenox shells out to `adb`, `flutter`, `scrcpy` and
  `tmux`. Device names, app names, IP addresses and config values that reach a
  shell unsanitised are in scope.
- **The installers.** `install.sh` and `install.ps1`, including where they write,
  what they add to `PATH`, and what they back up.
- **Config handling.** `~/.fenox.json` is parsed as JSON and backed up on
  corruption; anything that could make a config file execute code is in scope.

## Out of scope

- Vulnerabilities in `adb`, `flutter`, `scrcpy` or `tmux` themselves — report
  those upstream.
- Anything that requires an attacker to already have write access to your user
  account or your `~/.fenox.json`.
- A malicious *release* published by the maintainer account — that is a broader
  account-security matter, not a code vulnerability.

## How releases are protected

- Release artifacts are built by GitHub Actions from a tagged commit, never
  uploaded by hand.
- Each binary ships with a `.sha256` file and an aggregate `SHA256SUMS`.
- Both installers and the self-updater verify the checksum and **refuse to
  install** when no checksum is published or when it does not match.
- The Release workflow runs the end-to-end install test — including a tampered
  download that must be rejected — before publishing anything.
