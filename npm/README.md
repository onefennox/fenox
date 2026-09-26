# fenox

Android device management and Flutter development, from the browser.

This is the **npm entry point** for [Fenox](https://github.com/onefennox/fenox) — a
single-user, self-hosted web app that connects to Android phones over wireless or
USB debugging and lets you run, watch and hot-reload your Flutter apps on them
without opening a terminal.

```bash
npm install -g fenox
fenox doctor      # see what works on your machine, and what to fix
fenox             # start the hub and open the dashboard
```

## What this package is

Fenox itself is a Python application. This package is a small launcher: on the
first run it makes sure [uv](https://github.com/astral-sh/uv) is available, uses
it to install Fenox as an isolated tool, and from then on just executes it. Every
run after that costs one Node start-up (about 0.3s) and nothing else.

You do not need Python installed. uv fetches and manages a suitable one.

If you already have a Fenox — from the shell installer, `uv tool install`, or
`pipx` — this launcher will use that one and leave it alone. Installing this
package never replaces an existing installation.

## Requirements

- Linux, WSL2, macOS or Windows
- Node.js 18 or newer
- `adb` (Android Platform Tools) and the Flutter SDK, for talking to phones and
  building apps. Run `fenox doctor` and it will tell you precisely what is
  missing and how to install it.

Fenox needs to reach the host's adb, USB devices and Flutter SDK, which is why it
runs natively rather than in a container.

## Other ways to install

The npm package is one of several supported routes:

```bash
# shell installer (Linux / WSL)
curl -fsSL https://raw.githubusercontent.com/onefennox/fenox/main/packaging/install.sh | bash

# uv
uv tool install "fenox @ git+https://github.com/onefennox/fenox"

# from a checkout
git clone https://github.com/onefennox/fenox.git && bash fenox/packaging/install.sh
```

## Licence

MIT
