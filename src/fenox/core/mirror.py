"""Screen mirroring through the scrcpy server.

The hub runs the scrcpy server that ships with the installed `scrcpy`, pushes it
to the device, starts it, and proxies the raw video socket over a WebSocket. The
hub never decodes video — the browser does, with WebCodecs. Input is not sent
over the scrcpy control channel; it goes through the toolbox input actions, which
keeps one code path for device input.

The wire format implemented here is the scrcpy 1.x protocol: a 64-byte device
name, then a 12-byte codec header, then frame headers of an 8-byte timestamp and
a 4-byte size followed by the H.264 payload. `send_frame_meta` is requested from
the server, so frames are length-delimited.
"""
from __future__ import annotations

import os
import shutil
import socket
import struct
import subprocess
import time

SOCKET_NAME = "scrcpy"
DEVICE_NAME_SIZE = 64
CODEC_META_SIZE = 12
FRAME_HEADER_SIZE = 12
SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"

_VERSION_CACHE: str | None = None


def scrcpy_binary() -> str | None:
    return shutil.which("scrcpy")


def scrcpy_version() -> str | None:
    """The installed scrcpy version, or None when scrcpy is absent."""
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
    """Locate the scrcpy-server jar that ships with the installed scrcpy."""
    binary = scrcpy_binary()
    candidates = []
    if binary:
        prefix = os.path.dirname(os.path.dirname(os.path.realpath(binary)))
        candidates += [os.path.join(prefix, "share", "scrcpy", "scrcpy-server")]
    candidates += [
        "/usr/share/scrcpy/scrcpy-server",
        "/usr/local/share/scrcpy/scrcpy-server",
        "/opt/scrcpy/scrcpy-server",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def available() -> tuple[bool, str]:
    """Whether mirroring can run, with the reason when it cannot."""
    if not scrcpy_binary():
        return False, "scrcpy is not installed"
    if scrcpy_version() is None:
        return False, "the scrcpy version could not be read"
    if not server_path():
        return False, "the scrcpy-server jar was not found"
    return True, ""


def server_argv(version: str, max_size: int = 0, bit_rate: int = 8_000_000, max_fps: int = 0) -> list[str]:
    """The `adb shell` arguments that start the scrcpy server (1.x argument order).

    Version, log level, max size, bit rate, max fps, lock orientation, tunnel
    forward, crop, send frame meta, control. Tunnel forward is false so the server
    listens on an abstract socket the hub reaches through `adb forward`; control
    is false because input uses the toolbox actions instead.
    """
    return [
        "shell",
        f"CLASSPATH={SERVER_REMOTE_PATH}",
        "app_process", "/", "com.genymobile.scrcpy.Server",
        version, "info",
        str(max_size), str(bit_rate), str(max_fps),
        "-1", "false", "-", "true", "false",
    ]


def parse_codec_meta(data: bytes) -> dict:
    """The 12-byte codec header as {codec, width, height}."""
    if len(data) < CODEC_META_SIZE:
        raise ValueError("short codec metadata")
    codec, width, height = struct.unpack(">4sII", data[:CODEC_META_SIZE])
    return {"codec": codec.decode("ascii", "replace"), "width": width, "height": height}


class MirrorSession:
    """One running scrcpy server and its video socket."""

    def __init__(self, serial: str, max_size: int = 0, bit_rate: int = 8_000_000, max_fps: int = 0):
        self.serial = serial
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.max_fps = max_fps
        self.device_name: str = ""
        self.width = 0
        self.height = 0
        self.codec = ""
        self._server: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._port = 0
        self.started = False

    def _forward_port(self) -> int:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def start(self) -> None:
        version = scrcpy_version()
        if version is None:
            raise RuntimeError("scrcpy is not installed")
        jar = server_path()
        if jar is None:
            raise RuntimeError("the scrcpy-server jar was not found")

        _adb(self.serial, ["push", jar, SERVER_REMOTE_PATH], timeout=120)
        self._server = subprocess.Popen(
            ["adb", "-s", self.serial, *server_argv(version, self.max_size, self.bit_rate, self.max_fps)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

        self._port = self._forward_port()
        _adb(self.serial, ["forward", f"tcp:{self._port}", f"localabstract:{SOCKET_NAME}"], timeout=30)

        deadline = time.time() + 15
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                self._sock = socket.create_connection(("127.0.0.1", self._port), timeout=5)
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.3)
        if self._sock is None:
            self.stop()
            raise RuntimeError(f"could not connect to the scrcpy server: {last_error}")

        name = _recv_exact(self._sock, DEVICE_NAME_SIZE)
        meta_raw = _recv_exact(self._sock, CODEC_META_SIZE)
        if name is None or meta_raw is None:
            self.stop()
            raise RuntimeError("the scrcpy server closed before sending its metadata")
        self.device_name = name.split(b"\x00", 1)[0].decode("utf-8", "replace")
        meta = parse_codec_meta(meta_raw)
        self.codec = meta["codec"]
        self.width = meta["width"]
        self.height = meta["height"]
        self.started = True

    def read_frame(self) -> bytes | None:
        """The next `[12-byte header][payload]` frame, or None when the stream ends."""
        if self._sock is None:
            return None
        header = _recv_exact(self._sock, FRAME_HEADER_SIZE, allow_eof=True)
        if header is None:
            return None
        _pts, size = struct.unpack(">QI", header)
        payload = _recv_exact(self._sock, size, allow_eof=True)
        if payload is None:
            return None
        return header + payload

    def meta(self) -> dict:
        return {
            "device": self.device_name,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
        }

    def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
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
            _adb(self.serial, ["forward", "--remove", f"tcp:{self._port}"], timeout=10)
        self.started = False


def _adb(serial: str, args: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            ["adb", "-s", serial, *args],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return (proc.stdout + proc.stderr).strip()


def _recv_exact(sock: socket.socket, size: int, allow_eof: bool = False) -> bytes | None:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = sock.recv(size - len(buffer))
        if not chunk:
            if allow_eof and not buffer:
                return None
            raise ConnectionError("the scrcpy stream closed early")
        buffer += chunk
    return bytes(buffer)
