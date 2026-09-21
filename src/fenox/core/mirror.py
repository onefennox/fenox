"""Screen mirroring: scrcpy H.264 -> ffmpeg (fragmented MP4) -> the browser.

The device's hardware H.264 is passed through untouched. ffmpeg remuxes the raw
scrcpy stream into fragmented MP4 and the hub streams those bytes to the browser
over the same WebSocket the app already uses, where a native <video> element
plays them through Media Source Extensions. The hub never decodes video, and no
extra ports or WebRTC negotiation are involved.

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

from . import host, scrcpy_server

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


def codec_string(annexb: bytes) -> str:
    """The WebCodecs/MSE codec string for an Annex B H.264 stream.

    Reads profile, constraints and level from the Sequence Parameter Set so the
    browser accepts the fMP4 it is about to receive.
    """
    marker = b"\x00\x00\x00\x01\x67"
    index = annexb.find(marker)
    if index == -1 or index + 7 >= len(annexb):
        return "avc1.42E01E"
    profile, constraints, level = annexb[index + 5], annexb[index + 6], annexb[index + 7]
    return f"avc1.{profile:02x}{constraints:02x}{level:02x}"


def available(data_dir: Path | str | None = None) -> tuple[bool, str]:
    if host.adb_client() is None:
        return False, "adb was not found on this machine"
    if shutil.which("ffmpeg") is None:
        return False, "ffmpeg was not found on this machine"
    return True, ""


def _port_arg() -> int:
    from . import adb
    return adb.current_port() or adb.server_port()


class MirrorSession:
    """scrcpy + ffmpeg producing fragmented MP4 for one device."""

    def __init__(self, serial: str, device_id: str, data_dir: Path | str, version: str | None = None):
        self.serial = serial
        self.path = path_for(device_id)
        self.data_dir = Path(data_dir)
        self.version = version or scrcpy_server.PINNED_VERSION
        self.codec = "avc1.42E01E"
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
        jar = scrcpy_server.ensure(self.data_dir, self.version)

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

        # Sniff the first bytes for the SPS so the browser knows the codec.
        first = self._sock.recv(65536)
        if not first:
            self.stop()
            raise RuntimeError("the scrcpy stream sent no data")
        self.codec = codec_string(first)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.stop()
            raise RuntimeError("ffmpeg was not found")
        log_dir = self.data_dir / "mirror"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log = open(log_dir / f"{self.path}.ffmpeg.log", "wb")
        self._ffmpeg = subprocess.Popen(
            # Raw H.264 carries no timestamps, so ffmpeg uses wallclock time; the
            # probe stays smaller than the live stream so ffmpeg never waits for
            # data that will not come. Output is fragmented MP4 the browser can
            # append to a MediaSource buffer.
            [ffmpeg, "-hide_banner", "-loglevel", "warning",
             "-use_wallclock_as_timestamps", "1",
             "-probesize", "65536", "-analyzeduration", "0",
             "-f", "h264", "-i", "pipe:0",
             "-c:v", "copy",
             "-movflags", "frag_keyframe+empty_moov+default_base_moof",
             "-f", "mp4", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
        )
        # Feed the sniffed bytes, then the rest of the stream.
        assert self._ffmpeg.stdin is not None
        try:
            self._ffmpeg.stdin.write(first)
            self._ffmpeg.stdin.flush()
        except OSError:
            pass
        self._pump = threading.Thread(target=self._pump_socket, daemon=True, name=f"fenox-mirror-{self.path}")
        self._pump.start()

    def _pump_socket(self) -> None:
        sock = self._sock
        ffmpeg = self._ffmpeg
        if sock is None or ffmpeg is None or ffmpeg.stdin is None:
            return
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
                ffmpeg.stdin.close()
            except OSError:
                pass

    def read(self, size: int = 65536) -> bytes:
        """The next fragment of MP4 from ffmpeg, or b"" when it ends."""
        if self._ffmpeg is None or self._ffmpeg.stdout is None:
            return b""
        stream = self._ffmpeg.stdout
        read = getattr(stream, "read1", None) or stream.read
        try:
            return read(size)
        except (OSError, ValueError):
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
