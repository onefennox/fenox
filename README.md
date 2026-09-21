# Fenox

A single-user, self-hosted web app for Android devices and Flutter development.

Install Fenox, open it in a browser, and connect as many phones as you want over
USB or wireless debugging. Manage each device completely — screen, input, apps,
files, diagnostics, and the phone's own data — then register your Flutter
projects, run them on any connected device, watch them live, and hot reload,
hot restart, or stop them, all without leaving the browser.

## Status

**Design phase.** The architecture is being finalized in
[`docs/SPEC.md`](docs/SPEC.md). No implementation yet.

## Highlights

- **One process, one port** — the dashboard, REST API, and WebSocket live server
  are served together.
- **Plug and play** — USB, emulator, and wireless-debugging phones appear on
  their own and reconnect automatically.
- **Real hot reload** — the browser drives Flutter's own `SIGUSR1`/`SIGUSR2`
  control path, not a terminal emulation hack.
- **Full device control** — mirror, screenshot, record, type, tap, swipe, apps,
  files, shell, logcat, battery, network, storage, notifications.
- **Your phone's data** — messages, calls, contacts, and calendar, read straight
  from the phone with no root and nothing installed on it.
- **Single owner** — log in once; there are no accounts to create.

## Install

```bash
# From a checkout
bash packaging/install.sh

# One-liner (from the published repository)
curl -fsSL https://raw.githubusercontent.com/onefenox/fenox/main/packaging/install.sh | bash
```

The installer creates a private virtual environment under the data directory,
installs a `fenox` launcher on `PATH`, and can install a systemd `--user` service.

```bash
fenox                    # start the hub and open the dashboard
fenox serve --no-browser # headless (services, Docker)
fenox auth reset         # recover the owner credential
fenox info               # configuration and environment
```

## Configuration

Set via the environment; stored under the data directory.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FENOX_PORT` | `8787` | HTTP port |
| `FENOX_HOST` | `127.0.0.1` | Bind address |
| `FENOX_DATA_DIR` | `$XDG_DATA_HOME/fenox` | Data and database location |
| `FENOX_LOG_LEVEL` | `info` | Log verbosity |

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
cd web && npm run dev                    # dev server on :5173, proxies to :8787
```

The full design lives in [`docs/SPEC.md`](docs/SPEC.md).

## License

MIT — see [`LICENSE`](LICENSE).
