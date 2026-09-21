"""The transport between the hub and a running `flutter run` process.

Two control strategies exist, and the supervisor should not care which is in
use:

* POSIX — the child runs under a pseudo-terminal, and Flutter's `--pid-file`
  handler turns SIGUSR1 into a hot reload and SIGUSR2 into a hot restart. This is
  the supported path on Linux and WSL.
* stdin — on platforms without POSIX signals (Windows), the same keys Flutter
  reads from an interactive terminal (`r` and `R`) are written to the process.

`create_io` picks the right one. Adding a ConPTY-backed implementation for
Windows is then a matter of adding a class, not changing the supervisor.
"""
from __future__ import annotations

import os
import pty
import signal
import subprocess
from abc import ABC, abstractmethod


class SessionIO(ABC):
    #: whether the process can be controlled with POSIX signals
    supports_signals = False

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def read(self, size: int = 8192) -> bytes:
        """Bytes from the child, or b"" when the stream ends."""

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def signal_group(self, number: int) -> None:
        """Send a signal to the child's process group, if supported."""

    @abstractmethod
    def poll(self) -> int | None: ...

    @abstractmethod
    def wait(self, timeout: float | None = None) -> int | None: ...

    @abstractmethod
    def close(self) -> None: ...


class PosixPtyIO(SessionIO):
    """A pseudo-terminal child, controlled with signals."""

    supports_signals = True

    def __init__(self, argv: list[str], cwd: str, env: dict):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.pid: int | None = None
        self._master: int | None = None
        self._popen: subprocess.Popen | None = None

    def start(self) -> None:
        master, slave = pty.openpty()
        self._popen = subprocess.Popen(
            self.argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=self.cwd,
            env=self.env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self._master = master
        self.pid = self._popen.pid

    def read(self, size: int = 8192) -> bytes:
        if self._master is None:
            return b""
        try:
            return os.read(self._master, size)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        if self._master is not None:
            try:
                os.write(self._master, data)
            except OSError:
                pass

    def signal_group(self, number: int) -> None:
        if self._popen is None:
            return
        try:
            os.killpg(os.getpgid(self._popen.pid), number)
        except (ProcessLookupError, PermissionError):
            pass

    def poll(self) -> int | None:
        return self._popen.poll() if self._popen else None

    def wait(self, timeout: float | None = None) -> int | None:
        if self._popen is None:
            return None
        try:
            return self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None


class PipeIO(SessionIO):
    """A plain pipe child, controlled by writing keys to stdin.

    Used where a pseudo-terminal is unavailable; the run supervisor is otherwise
    unchanged.
    """

    supports_signals = False

    def __init__(self, argv: list[str], cwd: str, env: dict):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.pid: int | None = None
        self._popen: subprocess.Popen | None = None

    def start(self) -> None:
        self._popen = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.cwd,
            env=self.env,
        )
        self.pid = self._popen.pid

    def read(self, size: int = 8192) -> bytes:
        if self._popen is None or self._popen.stdout is None:
            return b""
        try:
            return self._popen.stdout.read1(size) if hasattr(self._popen.stdout, "read1") else self._popen.stdout.read(size)
        except Exception:
            return b""

    def write(self, data: bytes) -> None:
        if self._popen is not None and self._popen.stdin is not None:
            try:
                self._popen.stdin.write(data)
                self._popen.stdin.flush()
            except OSError:
                pass

    def signal_group(self, number: int) -> None:
        if self._popen is not None:
            try:
                self._popen.send_signal(number)
            except Exception:
                pass

    def poll(self) -> int | None:
        return self._popen.poll() if self._popen else None

    def wait(self, timeout: float | None = None) -> int | None:
        if self._popen is None:
            return None
        try:
            return self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        for stream in (self._popen.stdin if self._popen else None, self._popen.stdout if self._popen else None):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


def create_io(argv: list[str], cwd: str, env: dict) -> SessionIO:
    """Pick the transport for this platform."""
    if os.name == "posix" and hasattr(pty, "openpty"):
        return PosixPtyIO(argv, cwd, env)
    return PipeIO(argv, cwd, env)


# Re-exported so the supervisor can stop a process group portably.
SIGINT = getattr(signal, "SIGINT", 2)
SIGTERM = getattr(signal, "SIGTERM", 15)
SIGKILL = getattr(signal, "SIGKILL", 9)
