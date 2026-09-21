"""The `fenox` command.

The terminal is the management surface: start the hub, manage its service, check
system readiness, recover the owner credential, and update. Day-to-day device and
Flutter work lives in the web application.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from ..core import access, doctor
from ..core.auth import AuthStore
from ..core.config import Store, get_store
from ..version import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
SERVICE_NAME = "fenox.service"
REPO_URL = "https://github.com/onefenox/fenox.git"
CONFIG_KEYS = ("reach", "port", "remote_domain", "projects_dir", "flutter_path", "adb_path", "adb_port")
INT_KEYS = {"port", "adb_port"}


def _resolve_bind(args: argparse.Namespace) -> tuple[str, int]:
    store = get_store()
    reach = str(store.settings.get("reach") or "local")
    host = args.host or access.bind_host(reach)
    port = args.port or int(store.settings.get("port") or DEFAULT_PORT)
    return host, port


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    host, port = _resolve_bind(args)
    url_host = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"{'https' if args.tls_cert else 'http'}://{url_host}:{port}"

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    tls_cert = args.tls_cert or os.environ.get("FENOX_TLS_CERT")
    tls_key = args.tls_key or os.environ.get("FENOX_TLS_KEY")

    print(f"Fenox {__version__} serving on {url}")
    if tls_cert:
        print(f"  TLS: {tls_cert}")
    uvicorn.run(
        "fenox.server.app:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=args.log_level,
        ssl_certfile=tls_cert,
        ssl_keyfile=tls_key,
    )
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
    store = Store().load()
    reach = str(store.settings.get("reach") or "local")
    port = int(store.settings.get("port") or DEFAULT_PORT)
    resolved = doctor.tools(store.settings)
    print(f"Fenox {__version__}")
    print(f"  data directory : {store.paths.data}")
    print(f"  database       : {store.paths.db}")
    print(f"  owner set      : {AuthStore(store.paths.auth).has_owner()}")
    print(f"  reach          : {reach} ({access.REACH_LABELS.get(reach, reach)})")
    print(f"  urls           : {', '.join(access.urls(reach, port))}")
    print(f"  os             : {resolved['os']}")
    print(f"  adb (client)   : {resolved['adb']['client'] or 'not found'}")
    print(f"  flutter        : {resolved['flutter']['path'] or 'not found'}")
    print(f"  scrcpy server  : {resolved['scrcpy']['server'] or 'not found'}")
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    store = get_store()
    resolved = doctor.tools(store.settings)
    report = doctor.checks(store.settings)

    print(f"Fenox {__version__} environment")
    print(f"  os             : {resolved['os']}")
    print(f"  adb (client)   : {resolved['adb']['client'] or 'not found'}")
    print(f"  adb (server)   : {resolved['adb']['server'] or 'not found'}")
    print(f"  flutter        : {resolved['flutter']['path'] or 'not found'}")
    scrcpy = resolved["scrcpy"]
    version = f" ({scrcpy['version']})" if scrcpy.get("version") else ""
    print(f"  scrcpy         : {scrcpy['binary'] or 'not found'}{version}")
    print(f"  scrcpy server  : {scrcpy['server'] or 'not found'}")
    print()
    for tool in report["tools"]:
        state = "ok" if tool["present"] else ("missing" if tool["required"] else "optional")
        print(f"  [{state:>8}] {tool['name']:<12} {tool['version']}")

    if not resolved["flutter"]["path"]:
        print("\nFlutter was not found. Set its location with:")
        print("  fenox config set flutter_path /path/to/flutter")
    for note in report["notes"]:
        print(f"\n  {note['text']}")
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    store = get_store()
    command = getattr(args, "config_command", None) or "list"
    if command == "list":
        for key in CONFIG_KEYS:
            print(f"{key} = {store.settings.get(key)}")
        return 0
    if command == "get":
        print(store.settings.get(args.key, ""))
        return 0
    if command == "set":
        if args.key not in CONFIG_KEYS:
            print(f"Unknown setting: {args.key}", file=sys.stderr)
            print(f"Known: {', '.join(CONFIG_KEYS)}", file=sys.stderr)
            return 2
        value: object = args.value
        if args.key in INT_KEYS:
            try:
                value = int(str(args.value))
            except ValueError:
                print(f"{args.key} must be a number", file=sys.stderr)
                return 2
        store.settings[args.key] = value
        print(f"{args.key} = {value}")
        return 0
    return 2


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME


def _cmd_service(args: argparse.Namespace) -> int:
    unit = _unit_path()
    if args.service_command == "uninstall":
        if unit.exists():
            unit.unlink()
            print(f"Removed {unit}")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        print("Run: systemctl --user stop fenox")
        return 0

    launcher = shutil.which("fenox") or str(Path(sys.argv[0]).resolve())
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(
        "[Unit]\n"
        "Description=Fenox hub\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={launcher} serve --no-browser\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "KillMode=mixed\n"
        "TimeoutStopSec=15\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print(f"Installed {unit}")
    print("Enable and start it with:")
    print("  systemctl --user enable --now fenox")
    return 0


def _cmd_update(_: argparse.Namespace) -> int:
    import importlib.metadata as metadata

    source = f"fenox @ git+{REPO_URL}"
    try:
        direct = metadata.distribution("fenox").read_text("direct_url.json")
        if direct:
            data = json.loads(direct)
            if data.get("url") and data.get("dir_info") is not None:
                source = data["url"]
            elif data.get("url", "").startswith("https://github.com"):
                source = f"fenox @ git+{data['url']}"
    except Exception:
        pass

    print(f"Updating Fenox from {source}")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", source])
    if result.returncode == 0:
        print("Updated. Restart the hub to apply: systemctl --user restart fenox")
    return result.returncode


def _cmd_settings(_: argparse.Namespace) -> int:
    store = get_store()
    reach = str(store.settings.get("reach") or "local")
    port = int(store.settings.get("port") or DEFAULT_PORT)
    print(f"reach          : {reach}")
    print(f"port           : {port}")
    print(f"remote domain  : {store.settings.get('remote_domain') or '(none)'}")
    print(f"urls           : {', '.join(access.urls(reach, port))}")
    for note in access.notes(reach):
        print(f"  - {note}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fenox",
        description="Android device management and Flutter development, from the browser.",
    )
    parser.add_argument("--version", action="version", version=f"fenox {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the Fenox hub")
    serve.add_argument("--host", default=None, help="Bind address (default: from reach setting)")
    serve.add_argument("--port", type=int, default=None, help="Port (default: from settings)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    serve.add_argument("--reload", action="store_true", help="Reload on code changes (development)")
    serve.add_argument("--tls-cert", default=None, help="TLS certificate (or FENOX_TLS_CERT)")
    serve.add_argument("--tls-key", default=None, help="TLS private key (or FENOX_TLS_KEY)")
    serve.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug", "trace"])
    serve.set_defaults(func=_cmd_serve)

    auth = sub.add_parser("auth", help="Owner credential management")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    reset = auth_sub.add_parser("reset", help="Clear the owner credential (local recovery)")
    reset.add_argument("--yes", action="store_true", help="Do not prompt for confirmation")
    reset.set_defaults(func=_cmd_auth_reset)

    service = sub.add_parser("service", help="Manage the systemd user service")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_sub.add_parser("install", help="Install the systemd user service").set_defaults(func=_cmd_service)
    service_sub.add_parser("uninstall", help="Remove the systemd user service").set_defaults(func=_cmd_service)

    sub.add_parser("doctor", help="Detect adb, Flutter, scrcpy and other tools").set_defaults(func=_cmd_doctor)
    sub.add_parser("settings", help="Show reach, port, and URLs").set_defaults(func=_cmd_settings)
    sub.add_parser("update", help="Update Fenox to the latest version").set_defaults(func=_cmd_update)
    sub.add_parser("info", help="Show configuration and environment").set_defaults(func=_cmd_info)

    config = sub.add_parser("config", help="Read or set a setting")
    config_sub = config.add_subparsers(dest="config_command")
    config_sub.add_parser("list", help="List all settings").set_defaults(func=_cmd_config)
    config_get = config_sub.add_parser("get", help="Print one setting")
    config_get.add_argument("key")
    config_get.set_defaults(func=_cmd_config)
    config_set = config_sub.add_parser("set", help="Set one setting")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(func=_cmd_config)
    config.set_defaults(func=_cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["serve"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
