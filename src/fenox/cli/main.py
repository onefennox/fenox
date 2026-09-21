"""The `fenox` command.

The terminal is the management surface: start the hub, recover the owner
credential, and report system status. Day-to-day device and Flutter work lives in
the web application.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from ..core.auth import AuthStore
from ..core.config import Store, get_store
from ..version import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    host = args.host
    port = args.port
    url_host = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"http://{url_host}:{port}"

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"Fenox {__version__} serving on {url}")
    uvicorn.run("fenox.server.app:app", host=host, port=port, reload=args.reload, log_level=args.log_level)
    return 0


def _cmd_auth_reset(args: argparse.Namespace) -> int:
    store = get_store()
    auth = AuthStore(store.paths.auth)
    if not auth.has_owner():
        print("No owner credential is configured; nothing to reset.")
        return 0
    if not args.yes:
        answer = input("Reset the owner credential? You will set a new password on next open. [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1
    auth.reset()
    print("Owner credential cleared. Open the web app to set a new password.")
    return 0


def _cmd_info(_: argparse.Namespace) -> int:
    from ..core import host

    store = Store().load()
    print(f"Fenox {__version__}")
    print(f"  data directory : {store.paths.data}")
    print(f"  database       : {store.paths.db}")
    print(f"  owner set      : {AuthStore(store.paths.auth).has_owner()}")
    print(f"  platform       : {'WSL' if host.IS_WSL else 'Linux' if host.IS_LINUX else sys.platform}")
    print(f"  adb (Windows)  : {host.find_windows_adb() or 'not found'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fenox", description="Android device management and Flutter development, from the browser.")
    parser.add_argument("--version", action="version", version=f"fenox {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the Fenox hub")
    serve.add_argument("--host", default=DEFAULT_HOST, help="Bind address (default: %(default)s)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: %(default)s)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    serve.add_argument("--reload", action="store_true", help="Reload on code changes (development)")
    serve.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug", "trace"])
    serve.set_defaults(func=_cmd_serve)

    auth = sub.add_parser("auth", help="Owner credential management")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    reset = auth_sub.add_parser("reset", help="Clear the owner credential (local recovery)")
    reset.add_argument("--yes", action="store_true", help="Do not prompt for confirmation")
    reset.set_defaults(func=_cmd_auth_reset)

    info = sub.add_parser("info", help="Show configuration and environment")
    info.set_defaults(func=_cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # No subcommand: start the hub, which is the default action.
        args = parser.parse_args(["serve"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
