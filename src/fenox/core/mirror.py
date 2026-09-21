"""Screen mirroring through an official scrcpy-server.

Fenox provisions and pins its own scrcpy-server (see `scrcpy_server`) so
mirroring does not depend on whatever the host's `scrcpy` package happens to
ship. The hub pushes that server, opens scrcpy's default reverse tunnel, and
proxies the raw video socket to the browser, which parses and decodes it with
the Tango scrcpy client.

Tunnel facts, from the server's own behavior (v3.3.3):

* With `scid=-1` the abstract socket is named `scrcpy`.
* With `tunnel_forward=false` (the default) the server *connects out* to that
  socket, for video, then audio, then control. The hub listens locally and maps
  the device socket to it with `adb reverse localabstract:scrcpy tcp:PORT`.
* With `send_device_meta`/`send_codec_meta` the stream begins with a 64-byte
  device name and a 12-byte codec header; the browser's client consumes them.

Audio and the scrcpy control channel are disabled: input goes through the
toolbox actions, so one code path drives the device with or without mirroring.
"""
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess
from pathlib import Path

from . import host, scrcpy_server

SOCKET_NAME = "scrcpy"
SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"
DEVICE_NAME_SIZE = 64
CODEC_META_SIZE = 12

_VERSION_CACHE: str | None = None


# --- locally installed scrcpy (used for discovery and as a fallback) --------

def scrcpy_binary() -> str | None:
    return shutil.which("scrcpy")


def scrcpy_version() -> str | None:
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE or None
    binary = scrcpy_binary()
    if not binary:
        _VERSION_CACHE = ""
        return None
    try:
        output = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        _VERSION_CACHE = ""
        return None
    for token in output.replace("\n", " ").split():
        if token and token[0].isdigit() and token.count(".") >= 1:
            _VERSION_CACHE = token
            return token
    _VERSION_CACHE = ""
    return None


def server_path() -> str | None:
    binary = scrcpy_binary()
    candidates: list[str] = []
    if binary:
        real = os.path.realpath(binary)
        prefix = os.path.dirname(os.path.dirname(real))
        candidates += [
            os.path.join(prefix, "share", "scrcpy", "scrcpy-server"),
            os.path.join(os.path.dirname(real), "scrcpy-server"),
        ]
    candidates += [
        "/usr/share/scrcpy/scrcpy-server",
        "/usr/local/share/scrcpy/scrcpy-server",
        "/snap/scrcpy/current/usr/local/share/scrcpy/scrcpy-server",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


# --- protocol helpers -------------------------------------------------------

def server_args(version: str, *, audio: bool = False, control: bool = False) -> list[str]:
    """Server options as the 2.x/3.x server accepts them.

    The first argument must be the exact server version. `cleanup=false` keeps
    the server from deleting its own jar, which would break the next start.
    """
    return [
        version,
        f"audio={'true' if audio else 'false'}",
        f"control={'true' if control else 'false'}",
        "cleanup=false",
        "log_level=info",
    ]


def parse_codec_meta(data: bytes) -> dict:
    if len(data) < CODEC_META_SIZE:
        raise ValueError("short codec metadata")
    codec, width, height = struct.unpack(">4sII", data[:CODEC_META_SIZE])
    return {"codec": codec.decode("ascii", "replace"), "width": width, "height": height}


def available(cache_dir: Path | str | None = None) -> tuple[bool, str]:
    """Whether mirroring can run, with the reason when it cannot."""
    if host.adb_client() is None:
        return False, "adb was not found on this machine"
    override = os.environ.get("FENOX_SCRCPY_SERVER")
    if override and not os.path.isfile(override):
        return False, f"FENOX_SCRCPY_SERVER points at a missing file: {override}"
    return True, ""


def _port_arg() -> int:
    from . import adb
    return adb.current_port() or adb.server_port()


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = sock.recv(size - len(buffer))
        if not chunk:
            raise ConnectionError("the scrcpy stream closed early")
        buffer += chunk
    return bytes(buffer)


class MirrorSession:
    """One running scrcpy server and its video socket."""

    def __init__(self, serial: str, cache_dir: Path | str | None = None, version: str | None = None):
        self.serial = serial
        self.cache_dir = Path(cache_dir) if cache_dir else Path(os.environ.get("FENOX_DATA_DIR", "."))
        self.version = version or scrcpy_server.PINNED_VERSION
        self._server: subprocess.Popen | None = None
        self._listener: socket.socket | None = None
        self._sock: socket.socket | None = None
        self._port = 0
        self.started = False

    def _adb(self, args: list[str], timeout: int = 30) -> str:
        client = host.adb_client()
        if client is None:
            return "adb was not found"
        result = host.run([client, "-P", str(_port_arg()), "-s", self.serial, *args], timeout=timeout)
        return result.stdout or result.stderr

    def start(self) -> None:
        jar = scrcpy_server.ensure(self.cache_dir, self.version)

        pushed = self._adb(["push", str(jar), SERVER_REMOTE_PATH], timeout=120)
        if "1 file pushed" not in pushed:
            raise RuntimeError(pushed.strip() or "could not push the scrcpy server to the device")

        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(20)
        self._port = self._listener.getsockname()[1]

        self._adb(["reverse", f"localabstract:{SOCKET_NAME}", f"tcp:{self._port}"], timeout=30)

        binary = host.adb_client()
        if binary is None:
            self.stop()
            raise RuntimeError("adb was not found")
        self._server = subprocess.Popen(
            [binary, "-P", str(_port_arg()), "-s", self.serial, "shell",
             f"CLASSPATH={SERVER_REMOTE_PATH}", "app_process", "/",
             "com.genymobile.scrcpy.Server", *server_args(self.version)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

        try:
            self._sock, _ = self._listener.accept()
        except OSError as exc:
            self.stop()
            raise RuntimeError(f"the scrcpy server did not connect back: {exc}") from exc
        finally:
            if self._listener is not None:
                self._listener.close()
                self._listener = None
        self.started = True

    def read(self, size: int = 65536) -> bytes:
        """Raw bytes from the video socket, or b"" when the stream ends.

        The device name and codec header are not stripped: the browser client
        parses them itself.
        """
        if self._sock is None:
            return b""
        try:
            return self._sock.recv(size)
        except OSError:
            return b""

    def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        if self._server is not None:
            try:
                self._server.terminate()
                self._server.wait(timeout=5)
            except Exception:
                try:
                    self._server.kill()
                except Exception:
                    pass
            self._server = None
        if self._port:
            self._adb(["reverse", "--remove", f"localabstract:{SOCKET_NAME}"], timeout=10)
        self.started = False
