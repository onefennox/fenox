"""Screen mirroring: scrcpy H.264 -> ffmpeg -> MediaMTX -> WebRTC.

The device's hardware H.264 is passed through untouched: the scrcpy server runs
in raw mode (no device/codec/frame headers), ffmpeg remuxes the stream to RTSP
without re-encoding, and MediaMTX republishes it as WebRTC (WHEP) for the
browser. The hub does no video work.

The reverse tunnel is the one the scrcpy server expects: the hub listens, maps
the device's abstract socket to it with `adb reverse`, and the server connects
back.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import IO

from . import host, mediamtx, scrcpy_server

SOCKET_NAME = "scrcpy"
SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"

_VERSION_CACHE: str | None = None


# --- locally installed scrcpy (discovery only) ------------------------------

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


# --- helpers ----------------------------------------------------------------

def server_args(version: str, *, audio: bool = False, control: bool = False) -> list[str]:
    """Server options for a raw H.264 stream.

    `raw_stream=true` drops the device-name, codec and frame headers, so the
    socket is pure Annex B H.264 that ffmpeg can remux directly. `cleanup=false`
    keeps the server from deleting its own jar. The first argument must be the
    exact server version.
    """
    return [
        version,
        f"audio={'true' if audio else 'false'}",
        f"control={'true' if control else 'false'}",
        "raw_stream=true",
        "cleanup=false",
        "log_level=info",
    ]


def path_for(device_id: str) -> str:
    return "device_" + re.sub(r"[^A-Za-z0-9_]", "_", device_id)


def available(data_dir: Path | str | None = None) -> tuple[bool, str]:
    if host.adb_client() is None:
        return False, "adb was not found on this machine"
    if mediamtx.ffmpeg_binary() is None:
        return False, "ffmpeg was not found on this machine"
    override = os.environ.get("FENOX_MEDIAMTX")
    if override and not os.path.isfile(override):
        return False, f"FENOX_MEDIAMTX points at a missing file: {override}"
    return True, ""


def _port_arg() -> int:
    from . import adb
    return adb.current_port() or adb.server_port()


class MirrorSession:
    """scrcpy + ffmpeg publishing one device to MediaMTX."""

    def __init__(self, serial: str, device_id: str, mediamtx_server: mediamtx.MediaMTX,
                 version: str | None = None):
        self.serial = serial
        self.path = path_for(device_id)
        self.mediamtx = mediamtx_server
        self.version = version or scrcpy_server.PINNED_VERSION
        self._server: subprocess.Popen | None = None
        self._ffmpeg: subprocess.Popen | None = None
        self._listener: socket.socket | None = None
        self._sock: socket.socket | None = None
        self._pump: threading.Thread | None = None
        self._log: IO[bytes] | None = None
        self._port = 0

    def _adb(self, args: list[str], timeout: int = 30) -> str:
        client = host.adb_client()
        if client is None:
            return "adb was not found"
        result = host.run([client, "-P", str(_port_arg()), "-s", self.serial, *args], timeout=timeout)
        return result.stdout or result.stderr

    def start(self) -> None:
        self.mediamtx.start()
        jar = scrcpy_server.ensure(self.mediamtx.data_dir, self.version)

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

        ffmpeg = mediamtx.ffmpeg_binary()
        if ffmpeg is None:
            self.stop()
            raise RuntimeError("ffmpeg was not found")
        log_path = Path(self.mediamtx.data_dir) / "mirror"
        log_path.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_log = log_path / f"{self.path}.ffmpeg.log"
        self._log = open(self._ffmpeg_log, "wb")
        self._ffmpeg = subprocess.Popen(
            # Raw H.264 carries no timestamps, so ffmpeg must be told to use
            # wallclock time, and the probe must stay smaller than the stream or
            # ffmpeg waits for data that never comes and never opens the output.
            # This exact set is verified against the scrcpy raw stream on a pipe.
            [ffmpeg, "-hide_banner", "-loglevel", "warning",
             "-use_wallclock_as_timestamps", "1",
             "-probesize", "65536", "-analyzeduration", "0",
             "-f", "h264", "-i", "pipe:0",
             "-c:v", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
             f"rtsp://{mediamtx.RTSP_ADDRESS}/{self.path}"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log,
        )
        self._pump = threading.Thread(target=self._pipe, daemon=True, name=f"fenox-mirror-{self.path}")
        self._pump.start()

    def _pipe(self) -> None:
        """Copy the raw H.264 socket into ffmpeg until the stream ends."""
        sock = self._sock
        ffmpeg = self._ffmpeg
        assert sock is not None and ffmpeg is not None and ffmpeg.stdin is not None
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                ffmpeg.stdin.write(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                if ffmpeg.stdin:
                    ffmpeg.stdin.close()
            except OSError:
                pass

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
        if self._pump is not None:
            self._pump.join(timeout=3)
            self._pump = None
        if self._ffmpeg is not None:
            try:
                self._ffmpeg.terminate()
                self._ffmpeg.wait(timeout=5)
            except Exception:
                try:
                    self._ffmpeg.kill()
                except Exception:
                    pass
            self._ffmpeg = None
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None
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
