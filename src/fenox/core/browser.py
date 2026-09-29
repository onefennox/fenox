"""An embedded browser: a real Chrome, streamed to the dashboard.

Why a real browser rather than an iframe. An iframe is the obvious way to show a
page in Fenox and it does use the browser's own session — but a great many sites
refuse to be framed at all, via `X-Frame-Options` or a `frame-ancestors` policy
the browser enforces. Nothing in the frontend can work around that, and the
result is an unexplained blank rectangle.

So instead Fenox runs its own Chrome and shows you its screen. Every site loads,
because nothing is being embedded — the page is a real page in a real browser,
streamed as frames, with clicks and typing sent back over the DevTools Protocol.
The same protocol provides device emulation, which is what makes the desktop /
tablet / mobile switch honest: it changes the real viewport, device pixel ratio
and touch flag, so the site serves the layout it would serve that device, rather
than resizing a window and hoping.

Two things worth knowing:

* It is a **separate profile**, not your everyday browser's. Chrome refuses to
  expose its default profile to remote debugging, so logging in here is a fresh
  start — but the profile persists in the data directory, so it is one login per
  site rather than one per session.
* Frames are video. Text is not selectable and the DOM is not reachable from the
  dashboard. That is the price of "every site works".

All coordination happens on the single page-level DevTools socket, because that
is where both the `Page` commands and their events — including screencast frames
— travel.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .log import get_logger

log = get_logger("browser")

#: Viewports offered in the UI. `mobile` is the flag that matters most: without
#: it a site serves its desktop layout into a narrow box, which looks like a bug
#: in Fenox rather than a missing setting.
DEVICES: dict[str, dict] = {
    "desktop": {"label": "Desktop", "width": 1440, "height": 900, "scale": 1, "mobile": False},
    "laptop": {"label": "Laptop", "width": 1280, "height": 800, "scale": 1, "mobile": False},
    "tablet": {"label": "Tablet", "width": 834, "height": 1112, "scale": 2, "mobile": True},
    "mobile": {"label": "Mobile", "width": 390, "height": 844, "scale": 3, "mobile": True},
}

DEFAULT_DEVICE = "desktop"

_CHROME_NAMES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "brave-browser",
)


def find_chrome() -> str | None:
    """The browser binary Fenox will drive, if one is installed."""
    explicit = os.environ.get("FENOX_CHROME")
    if explicit and os.path.exists(explicit):
        return explicit
    for name in _CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CdpError(RuntimeError):
    pass


@dataclass
class BrowserState:
    running: bool = False
    url: str = ""
    device: str = DEFAULT_DEVICE
    error: str = ""


class Browser:
    """One Chrome, launched on demand and kept for the life of the hub."""

    def __init__(self, profile_dir: Path):
        self.profile_dir = Path(profile_dir)
        self.process: subprocess.Popen | None = None
        self.port = 0
        #: The page-level DevTools socket; `websockets` has no exported client type here.
        self._ws: Any = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self._frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)
        #: Commands with no useful reply, drained by their own task. Sending them
        #: inline would make the read loop wait on the socket, and frames arrive
        #: far faster than command replies — which starved the replies and made
        #: every command time out while a stream was running.
        self._outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._sender: asyncio.Task | None = None
        self._screencasting = False
        self._start_lock = asyncio.Lock()
        self.state = BrowserState()

    def available(self) -> bool:
        return find_chrome() is not None

    # --- process ------------------------------------------------------------

    async def start(self) -> None:
        """Launch Chrome if needed and attach to a page. Safe to call often."""
        async with self._start_lock:
            if self.process and self.process.poll() is None and self._ws is not None:
                return

            binary = find_chrome()
            if binary is None:
                raise CdpError(
                    "No Chrome or Chromium was found. Install one, or point "
                    "FENOX_CHROME at an existing binary."
                )

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self.port = _free_port()
            # Every flag here is load-bearing:
            #   --headless                 no display to render into on a server or in WSL
            #   --remote-debugging-port    the whole mechanism
            #   --user-data-dir            a persistent profile, so logins survive
            #   --no-first-run             no interactive prompts on a fresh profile
            args = [
                binary,
                "--headless",
                f"--remote-debugging-port={self.port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
            log.info("starting %s (port %s)", Path(binary).name, self.port)
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

            await self._wait_for_devtools()
            page_ws = self._new_page()

            import websockets

            self._ws = await websockets.connect(page_ws, max_size=64_000_000)
            self._reader = asyncio.create_task(self._read_loop())
            self._sender = asyncio.create_task(self._send_loop())
            self._next_id = 0
            self._pending.clear()
            self._screencasting = False
            self.state = BrowserState(running=True, device=DEFAULT_DEVICE)

    async def _wait_for_devtools(self, timeout: float = 30.0) -> None:
        """Poll until Chrome is listening, or give up with the reason."""
        deadline = asyncio.get_event_loop().time() + timeout
        last = "no response"
        while asyncio.get_event_loop().time() < deadline:
            if self.process and self.process.poll() is not None:
                raise CdpError("Chrome exited immediately after starting.")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=2
                ) as probe:
                    json.load(probe)
                return
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = str(exc)
                await asyncio.sleep(0.3)
        raise CdpError(f"Chrome never opened its debugging port: {last}")

    def _new_page(self) -> str:
        """A page-level DevTools socket. Chrome >= 111 requires PUT here."""
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT"
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return str(json.load(response)["webSocketDebuggerUrl"])
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            raise CdpError(f"could not open a browser tab: {exc}") from exc

    async def _read_loop(self) -> None:
        """Reply to callers, and hand screencast frames to the frame queue."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                if "id" in message:
                    future = self._pending.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                if message.get("method") == "Page.screencastFrame":
                    params = message.get("params", {})
                    log.debug("frame %s bytes", len(params.get("data", "")))
                    try:
                        self._frames.put_nowait(base64.b64decode(params.get("data", "")))
                    except asyncio.QueueFull:
                        pass  # viewer slower than the encoder: drop rather than lag
                    except Exception:
                        pass
                    session = params.get("sessionId")
                    if session is not None:
                        # Deliberately not sent through `_cmd`: that awaits a reply,
                        # and the reply can only be delivered by this very loop, so
                        # it would wait on itself. Chrome also stops streaming if
                        # acks stop arriving, so this must not block on anything.
                        await self._notify("Page.screencastFrameAck", {"sessionId": session})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Warn, not debug: if this loop stops, every later command times out
            # with no other clue as to why.
            log.warning("browser connection ended: %s", exc)
            self.state.running = False

    async def _notify(self, method: str, params: dict | None = None) -> None:
        """Queue a command that has no useful reply. Never blocks the caller."""
        try:
            self._outbox.put_nowait(json.dumps({"method": method, "params": params or {}}))
        except asyncio.QueueFull:
            pass  # a backlog of acks is worse than dropping one

    async def _send_loop(self) -> None:
        """Drain queued notifications. Runs beside the reader, not inside it."""
        try:
            while True:
                message = await self._outbox.get()
                if self._ws is None:
                    continue
                try:
                    await self._ws.send(message)
                except Exception as exc:
                    log.debug("could not send: %s", exc)
                    return
        except asyncio.CancelledError:
            raise

    async def _cmd(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        if self._ws is None:
            raise CdpError("the browser is not running")
        self._next_id += 1
        message_id = self._next_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[message_id] = future
        try:
            await self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        except Exception as exc:
            self._pending.pop(message_id, None)
            raise CdpError(f"could not talk to the browser: {exc}") from exc
        reply = await asyncio.wait_for(future, timeout=timeout)
        if "error" in reply:
            raise CdpError(str(reply["error"].get("message", reply["error"])))
        return reply

    # --- page operations ----------------------------------------------------

    async def navigate(self, url: str) -> None:
        target = _normalise(url)
        if not target:
            return
        await self._cmd("Page.enable")
        await self.set_device(self.state.device)  # re-applied per navigation; the override can drop
        await self._cmd("Page.navigate", {"url": target})
        self.state.url = target
        # A screencast asked for before the navigation commits is refused with
        # "Not attached to an active page", so restart it only once the new
        # document is in place.
        if self._screencasting:
            self._screencasting = False
            await self.start_screencast()

    async def set_device(self, device: str) -> None:
        spec = DEVICES.get(device) or DEVICES[DEFAULT_DEVICE]
        await self._cmd(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": int(spec["width"]),
                "height": int(spec["height"]),
                "deviceScaleFactor": int(spec["scale"]),
                "mobile": bool(spec["mobile"]),
            },
        )
        self.state.device = device

    async def start_screencast(self, attempts: int = 12) -> None:
        """Begin streaming frames, waiting out a navigation if one is in flight.

        Starting this immediately after `Page.navigate` reliably fails while the
        new document is still committing, so it is retried rather than made the
        caller's problem.
        """
        if self._screencasting:
            return
        spec = DEVICES.get(self.state.device) or DEVICES[DEFAULT_DEVICE]
        params = {
            "format": "jpeg",
            "quality": 70,
            # Matched to the emulated viewport so a frame pixel maps 1:1 to a page
            # pixel, which is what makes click coordinates exact.
            "maxWidth": int(spec["width"]),
            "maxHeight": int(spec["height"]),
            "everyNthFrame": 2,
        }
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                await self._cmd("Page.startScreencast", params)
                self._screencasting = True
                return
            except CdpError as exc:
                last = exc
                if "not attached" not in str(exc).lower():
                    raise
                await asyncio.sleep(0.25 * min(attempt + 1, 4))
        raise CdpError(f"could not start the screen stream: {last}")

    async def stop_screencast(self) -> None:
        if not self._screencasting:
            return
        try:
            await self._cmd("Page.stopScreencast")
        except Exception as exc:
            log.debug("stopScreencast: %s", exc)
        self._screencasting = False

    async def next_frame(self, timeout: float = 5.0) -> bytes:
        return await asyncio.wait_for(self._frames.get(), timeout=timeout)

    def clear_frames(self) -> None:
        while not self._frames.empty():
            try:
                self._frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def go_back(self) -> None:
        await self._cmd("Runtime.evaluate", {"expression": "history.back()"})

    async def reload(self) -> None:
        await self._cmd("Page.reload", {"ignoreCache": False})

    # --- input --------------------------------------------------------------

    async def click(self, x: float, y: float) -> None:
        for event in ("mousePressed", "mouseReleased"):
            await self._cmd(
                "Input.dispatchMouseEvent",
                {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    async def scroll(self, x: float, y: float, delta_y: float, delta_x: float = 0.0) -> None:
        await self._cmd(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": x, "y": y, "deltaX": delta_x, "deltaY": delta_y},
        )

    async def type_text(self, text: str) -> None:
        # insertText goes through the input path, so it reaches pages that listen
        # for input events as well as those reading key events.
        await self._cmd("Input.insertText", {"text": text})

    # --- lifecycle ----------------------------------------------------------

    async def stop(self) -> None:
        await self.stop_screencast()
        for task in (self._reader, self._sender):
            if task is not None:
                task.cancel()
        self._reader = None
        self._sender = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.state = BrowserState()


def _normalise(raw: str) -> str:
    target = (raw or "").strip()
    if not target:
        return ""
    if target.startswith(("http://", "https://")):
        return target
    if "." in target.split("/")[0]:
        return f"https://{target}"
    return f"https://duckduckgo.com/?q={target.replace(' ', '+')}"


_manager: Browser | None = None


def manager(profile_dir: Path) -> Browser:
    """The one browser this hub drives."""
    global _manager
    profile = Path(profile_dir)
    if _manager is None or _manager.profile_dir != profile:
        _manager = Browser(profile)
    return _manager
