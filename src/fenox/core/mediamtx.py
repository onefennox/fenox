"""Provisioning and running MediaMTX, the WebRTC media server.

Mirroring publishes the device's H.264 to MediaMTX over RTSP; the browser then
reads it over WebRTC (WHEP). MediaMTX is a single, dependency-free binary, so it
is downloaded and cached in the data directory exactly like the scrcpy server.

Fenox binds MediaMTX to loopback and proxies the WHEP handshake through the hub,
so the owner session still guards who can start a stream.
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PINNED_VERSION = os.environ.get("FENOX_MEDIAMTX_VERSION", "1.21.1")
RTSP_ADDRESS = "127.0.0.1:8554"
WEBRTC_ADDRESS = "127.0.0.1:8889"
WEBRTC_UDP_ADDRESS = "127.0.0.1:8189"
API_ADDRESS = "127.0.0.1:9997"

_ASSET = "https://github.com/bluenviron/mediamtx/releases/download/v{version}/mediamtx_v{version}_linux_{arch}.tar.gz"


class ProvisionError(RuntimeError):
    pass


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise ProvisionError(f"MediaMTX has no build for this architecture: {machine}")


def cache_dir(data_dir: Path | str, version: str = PINNED_VERSION) -> Path:
    return Path(data_dir) / "mediamtx" / f"v{version}-{_arch()}"


def binary_path(data_dir: Path | str, version: str = PINNED_VERSION) -> Path:
    return cache_dir(data_dir, version) / "mediamtx"


def cached(data_dir: Path | str, version: str = PINNED_VERSION) -> bool:
    binary = binary_path(data_dir, version)
    return binary.is_file() and os.access(binary, os.X_OK)


def download(version: str = PINNED_VERSION, timeout: int = 120) -> bytes:
    url = _ASSET.format(version=version, arch=_arch())
    request = urllib.request.Request(url, headers={"User-Agent": "fenox"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ProvisionError(f"could not download MediaMTX {version}: {exc}") from exc


def ensure(data_dir: Path | str, version: str = PINNED_VERSION) -> Path:
    override = os.environ.get("FENOX_MEDIAMTX")
    if override and os.path.isfile(override):
        return Path(override)

    target = binary_path(data_dir, version)
    if target.is_file() and os.access(target, os.X_OK):
        return target

    data = download(version)
    destination = cache_dir(data_dir, version)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = next((m for m in archive.getmembers() if m.name.endswith("mediamtx") and m.isfile()), None)
        if member is None:
            raise ProvisionError("the MediaMTX archive did not contain the binary")
        archive.extract(member, destination)
        extracted = destination / member.name
        if extracted != target:
            shutil.move(str(extracted), str(target))
    target.chmod(0o755)
    return target


def write_config(data_dir: Path | str) -> Path:
    """A minimal config: RTSP in, WebRTC (WHEP) out, everything else off."""
    path = Path(data_dir) / "mediamtx" / "mediamtx.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "logLevel: warn\n"
        "rtsp: yes\n"
        f"rtspAddress: {RTSP_ADDRESS}\n"
        "rtmp: no\n"
        "hls: no\n"
        "srt: no\n"
        "api: yes\n"
        f"apiAddress: {API_ADDRESS}\n"
        "webrtc: yes\n"
        f"webrtcAddress: {WEBRTC_ADDRESS}\n"
        f"webrtcLocalUDPAddress: {WEBRTC_UDP_ADDRESS}\n"
        f"webrtcLocalTCPAddress: {WEBRTC_UDP_ADDRESS}\n"
        "webrtcAdditionalHosts: [127.0.0.1]\n"
        "webrtcAllowOrigins: ['*']\n"
        "webrtcEncryption: no\n"
        "paths:\n"
        "  all_others:\n"
    )
    return path


class MediaMTX:
    """Runs one MediaMTX process for this hub."""

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.process: subprocess.Popen | None = None
        self.config: Path | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, version: str = PINNED_VERSION) -> None:
        if self.running:
            return
        binary = ensure(self.data_dir, version)
        self.config = write_config(self.data_dir)
        self.process = subprocess.Popen(
            [str(binary), str(self.config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        self._wait_ready()

    def _wait_ready(self, timeout: float = 8.0) -> None:
        import socket

        address = API_ADDRESS.rsplit(":", 1)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((address[0], int(address[1])), timeout=0.5):
                    return
            except OSError:
                if self.process is not None and self.process.poll() is not None:
                    raise ProvisionError("MediaMTX exited during startup") from None
                time.sleep(0.2)
        raise ProvisionError("MediaMTX did not become ready")

    def stop(self) -> None:
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    # -- WHEP -------------------------------------------------------------
    def whep(self, path: str, offer: str, timeout: int = 15) -> str:
        """Forward a WHEP offer to MediaMTX and return its answer SDP."""
        request = urllib.request.Request(
            f"http://{WEBRTC_ADDRESS}/{path}/whep",
            data=offer.encode(),
            headers={"Content-Type": "application/sdp"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            raise ProvisionError(f"MediaMTX rejected the WHEP offer: {exc.read().decode(errors='replace')[:200]}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ProvisionError(f"could not reach MediaMTX: {exc}") from exc


def ffmpeg_binary() -> str | None:
    return shutil.which("ffmpeg")
