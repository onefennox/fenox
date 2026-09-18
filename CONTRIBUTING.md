# Contributing to Fenox Mobile

Thanks for taking the time to contribute. This document covers how to get a
working checkout, what we expect from a change, and how releases are cut.

## Ways to contribute

- **Bug reports** — please use the bug report template. It asks for your version,
  platform and `fenox doctor` output, which is usually what we need to reproduce.
- **Feature requests** — open a feature request describing the problem, not just
  the solution. Small, focused proposals are much easier to merge.
- **Pull requests** — bug fixes and documentation are always welcome. For
  anything that changes the CLI surface or the config format, open an issue
  first so we can agree on the shape before you write the code.
- **Device reports** — if `fenox doctor` misbehaves on a specific phone, a
  report with the model, Android version and connection type is genuinely useful.

## Getting a working checkout

Fenox is one Python file (`src/fenox_mobile_source.py`), a bash installer and a
PowerShell installer. No build step is needed to run it from source:

```bash
git clone https://github.com/onefennox/fenox-mobile.git
cd fenox-mobile
pip install rich                 # the only runtime dependency
python3 src/fenox_mobile_source.py --help
```

Use a throwaway `$HOME` when you are experimenting, so your real config and
shell rc files are left alone:

```bash
mkdir -p /tmp/fenox-dev
HOME=/tmp/fenox-dev python3 src/fenox_mobile_source.py devices --json
```

To exercise the install path with a real binary, build one the way CI does and
point the end-to-end test at it:

```bash
pip install pyinstaller rich
pyinstaller --onefile --name fenox-mobile --distpath dist --workpath /tmp \
  --specpath /tmp src/fenox_mobile_source.py
bash tests/test_release_e2e.sh dist/fenox-mobile
```

## Before you open a pull request

Run the same checks CI runs:

```bash
python -m py_compile src/fenox_mobile_source.py
python src/fenox_mobile_source.py --help
python src/fenox_mobile_source.py devices --json < /dev/null
bash -n install.sh
bash tests/test_install_checksum.sh
python tests/test_version_key.py
```

If you changed `VERSION` or `FENOX_VERSION`, they must match — CI fails if they
drift apart.

## Project conventions

- **One file, on purpose.** `src/fenox_mobile_source.py` is the whole CLI. Keep
  it that way: a single file keeps the PyInstaller build trivial and the
  installer small. Group new code under an existing `# ---` section header.
- **No new runtime dependencies** without a good reason. `rich` is the only one.
  Anything else inflates the binary and the installer's supply chain.
- **Fail closed on integrity.** Anything that downloads or writes over an
  installed binary must verify a checksum first and refuse on mismatch. Never add
  a code path that installs an unverified artifact.
- **Ask before assuming paths.** Nothing should assume `~/Projects` exists — go
  through `get_projects_dir()`, which respects the user's configured directory.
- **Never delete anything outside the install.** `fenox uninstall` only ever
  removes genuine installs, the config, and fenox's own shell hooks. Keep it
  that way; a source checkout must never be a removal target.
- **Match the surrounding style.** Terse helpers, `rich` for all output, no bare
  `print()` for user-facing text.
- **Platform honesty.** Linux and Windows are supported; macOS is not. If a
  feature is Linux-only (for example `tmux` blast deploys), degrade clearly
  instead of crashing.

## Tests

| Suite | What it covers |
|---|---|
| `tests/test_install_checksum.sh` | Checksum resolution in `install.sh` — preference order, wrong-arch rejection, malformed files, refusal when nothing is published |
| `tests/test_version_key.py` | Numeric version comparison used by `fenox update` |
| `tests/test_release_e2e.sh` | The full release → install path against a real binary, over loopback HTTP |

New behaviour should come with a test that fails without your change.

## Commits and pull requests

- Keep commits focused; a subject line in the imperative mood and a body that
  explains **why**, not just what.
- Describe how you tested it. "Ran `tests/test_release_e2e.sh` against a locally
  built binary" is worth more than a summary of the diff.
- One logical change per pull request.

## Releases

Fenox follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Cutting a release:

1. Update `VERSION` and `FENOX_VERSION` in `src/fenox_mobile_source.py` — they
   must be identical.
2. Move the `Unreleased` entries in `CHANGELOG.md` under the new version and date.
3. Commit, then tag and push:

   ```bash
   git tag -a v1.1.0 -m "Fenox Mobile 1.1.0"
   git push origin v1.1.0
   ```

Pushing a `v*` tag is the entire release process. The Release workflow builds
Linux (x86_64 and aarch64) and Windows binaries, verifies each one runs, runs the
end-to-end install test against the Linux artifact, and only then publishes the
release with checksums. A failing install test blocks the release.
