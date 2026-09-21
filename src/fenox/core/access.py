"""Who can reach the hub, and on what address.

Three tiers, from the specification: `local` (this machine only), `lan` (the
local network, behind the owner login), and `remote` (through a tunnel or the
owner's own reverse proxy, always over TLS). The hub itself always requires the
owner; this module only decides what it binds to and what URLs to show.
"""
from __future__ import annotations

from . import adb

REACH_LEVELS = ("local", "lan", "remote")
REACH_LABELS = {
    "local": "This machine only",
    "lan": "Local network",
    "remote": "Remote (tunnel or proxy)",
}


def bind_host(reach: str) -> str:
    """The address uvicorn should bind for a reach tier."""
    return "0.0.0.0" if reach == "lan" else "127.0.0.1"


def is_valid(reach: str) -> bool:
    return reach in REACH_LEVELS


def urls(reach: str, port: int) -> list[str]:
    """The URLs a person can actually open for this reach tier."""
    if reach == "lan":
        ip = adb.local_ip()
        local = [f"http://localhost:{port}"]
        return local + ([f"http://{ip}:{port}"] if ip else [])
    if reach == "remote":
        return [f"http://localhost:{port}"]
    return [f"http://localhost:{port}"]


def notes(reach: str) -> list[str]:
    if reach == "lan":
        return [
            "Reachable from other devices on your network; the owner login still applies.",
            "Your firewall may need to allow the port.",
            "Restart Fenox for a bind change to take effect.",
        ]
    if reach == "remote":
        return [
            "Fenox keeps listening on localhost. Put a tunnel (for example cloudflared) or "
            "your own reverse proxy in front of it, with TLS.",
            "Never expose plain HTTP to the internet.",
        ]
    return ["Only this machine can reach the hub. This is the safe default."]
