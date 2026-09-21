"""Provisioning the scrcpy-server that runs on the device.

Fenox does not depend on whatever version the host's `scrcpy` package shipped.
It pins an official server release, caches it in the data directory, and pushes
it to the device. That keeps mirroring consistent on every machine.

Resolution order:
1. `FENOX_SCRCPY_SERVER` (explicit override)
2. The pinned server already cached in the data directory
3. A download of the pinned official release
4. The server that ships with a locally installed scrcpy (fallback)
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

#: The newest scrcpy protocol the browser client (Tango) implements.
PINNED_VERSION = os.environ.get("FENOX_SCRCPY_VERSION", "3.3.3")

_RELEASE_URL = "https://github.com/Genymobile/scrcpy/releases/download/v{version}/scrcpy-server-v{version}"
_MIN_SIZE = 50_000


class ProvisionError(RuntimeError):
    pass


def cache_path(cache_dir: Path | str, version: str = PINNED_VERSION) -> Path:
    return Path(cache_dir) / "scrcpy" / f"scrcpy-server-v{version}"


def download(version: str = PINNED_VERSION, timeout: int = 60) -> bytes:
    url = _RELEASE_URL.format(version=version)
    request = urllib.request.Request(url, headers={"User-Agent": "fenox"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ProvisionError(f"could not download scrcpy-server {version}: {exc}") from exc
    if len(data) < _MIN_SIZE:
        raise ProvisionError(f"downloaded scrcpy-server {version} looks too small ({len(data)} bytes)")
    return data


def ensure(cache_dir: Path | str, version: str = PINNED_VERSION, allow_download: bool = True) -> Path:
    """Return a server binary, downloading and caching the pinned release if needed."""
    override = os.environ.get("FENOX_SCRCPY_SERVER")
    if override and os.path.isfile(override):
        return Path(override)

    target = cache_path(cache_dir, version)
    if target.is_file() and target.stat().st_size >= _MIN_SIZE:
        return target

    if allow_download:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = download(version)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return target

    raise ProvisionError(f"scrcpy-server {version} is not cached")


def cached(cache_dir: Path | str, version: str = PINNED_VERSION) -> bool:
    target = cache_path(cache_dir, version)
    return target.is_file() and target.stat().st_size >= _MIN_SIZE
