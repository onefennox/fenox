#!/usr/bin/env python3
"""Session bookend tests: the opening screen, the sign-off, and how keys behave.

Drives the real CLI over a pseudo-terminal, so the single-keypress menus are
exercised the way a user experiences them rather than through piped input. Linux
only, like the product itself; it skips cleanly where pty is unavailable.

Regression guards:
  * the session must open with an environment summary and close with a sign-off,
    on every exit path (quit key, Ctrl+C, end of input)
  * ↑/↓ move the highlight and Enter commits it; Enter is never a no-op
  * Ctrl+C exits 130 instead of being swallowed by a menu
  * `--version` and `--generate-completions` stay instant and never start adb,
    because both run on every new shell
  * every child process gets /dev/null on stdin: a Windows interop call reading
    the terminal stole the user's next keypress in WSL
"""
import datetime
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "fenox.py")
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]|\x1b[=>]")

try:
    import fcntl
    import pty
    import struct
    import termios
except ImportError:                      # pragma: no cover - non-POSIX
    print("pty is unavailable on this platform — skipping session UI tests")
    sys.exit(0)

failures = []


def check(desc, ok, detail=""):
    info = f" ({detail})" if detail else ""
    if ok:
        print(f"  \033[32mok\033[0m   {desc}{info}")
    else:
        print(f"  \033[31mFAIL\033[0m {desc}{info}")
        failures.append(desc)


def clean(text):
    return ANSI.sub("", text)


# The input line's prompt is printed by every menu, so its arrival means the first
# screen is up and reading keys. Booting a session takes about 1.4s on this machine,
# which makes a fixed 2-6s wait per run most of this suite's runtime.
READY_PROMPT = "❯"
KEY_GAP = 0.8            # between keys: a screen has to be up before the next lands


def _run(home, keys, *, tty=True, cols=100, rows=44, settle=0.3, timeout=15,
         ready=READY_PROMPT, ready_timeout=12):
    """Start a session on a pty, send keys one at a time, return (output, exit code).

    The first key waits for the prompt rather than for a guessed delay, so a run
    costs its real boot time and nothing more; `settle` is a small cushion for the
    frame to finish drawing. Keys are then spaced by KEY_GAP, because a key meant
    for a screen that has not opened yet is taken by the one still running — `b` on
    the dashboard, for instance, means quit.
    """
    env = dict(os.environ, HOME=home, TERM="xterm-256color", COLUMNS=str(cols), LINES=str(rows))
    pid, fd = pty.fork()
    if pid == 0:                          # child
        if not tty:
            os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
        else:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.environ.update(env)
        os.execv(sys.executable, [sys.executable, SRC])

    out, timed_out = b"", False
    pending = list(keys)
    next_key = None
    deadline = time.monotonic() + timeout
    ready_by = time.monotonic() + ready_timeout
    while True:
        now = time.monotonic()
        if pending and next_key is None and (ready.encode() in out or now > ready_by):
            next_key = now + settle
        if pending and next_key is not None and now >= next_key:
            os.write(fd, pending.pop(0))
            next_key = now + KEY_GAP
        if select.select([fd], [], [], 0.2)[0]:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if now > deadline:
            timed_out = True
            os.kill(pid, 9)
            break

    time.sleep(0.3)
    while select.select([fd], [], [], 0.2)[0]:        # drain the pty
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    try:
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        code = None
    os.close(fd)
    return out.decode("utf-8", "replace"), (None if timed_out else code)


def make_home(*, configured=True, history=None):
    """A throwaway HOME. `configured` seeds one device, one app, one projects dir."""
    home = tempfile.mkdtemp(prefix="fenox-session-")
    projects = os.path.join(home, "demo")
    os.makedirs(projects, exist_ok=True)
    config = {"apps": {}, "devices": {},
              "settings": {"remote_domain": "", "projects_dir": projects}}
    if configured:
        config["apps"] = {"demo": {"path": projects, "port": "4000",
                                   "api_local": "http://localhost:4000/api"}}
        config["devices"] = {"myphone": {"ip": "192.168.1.50", "model": "Pixel 7", "port": "5555"}}
        config["settings"]["remote_domain"] = "demo.test"
    with open(os.path.join(home, ".fenox.json"), "w") as f:
        json.dump(config, f, indent=2)
    if history:
        with open(os.path.join(home, ".fenox_history.json"), "w") as f:
            f.write(history)
    return home


def quick(home, argv):
    start = time.monotonic()
    proc = subprocess.run([sys.executable, SRC] + argv, capture_output=True, text=True,
                          env=dict(os.environ, HOME=home), stdin=subprocess.DEVNULL)
    return proc, time.monotonic() - start


homes = []
try:
    # --- a configured session: opens, reports, quits on a key -------------------
    print("session opening and sign-off")
    home = homes.append(make_home()) or homes[-1]
    out, code = _run(home, [b"\r", b"b", b"x"])   # Enter opens the highlighted row
    text_enter = clean(out)
    check("Enter opens the highlighted row and never quits",
          "dashboard › device" in text_enter and "Session ended" in text_enter, f"exit={code}")
    home = homes.append(make_home()) or homes[-1]
    out, code = _run(home, [b"x"])
    text = clean(out)
    check("opening screen shows product + platform", "⚡ fenox v" in text and "ENVIRONMENT MANAGER" in text)
    check("opening screen lists environment checks",
          all(label in text for label in ("config", "adb server", "projects", "shell")))
    # Status belongs on the row itself, and each group of rows appears once —
    # no second table repeating what the list already says.
    device_rows = [line for line in text.splitlines() if "📱 myphone" in line]
    check("device status sits on its own row, grouped under headings",
          bool(device_rows) and "offline" in device_rows[0]
          and "DEVICES" in text and "APPS" in text)
    check("a single key quits, exit 0", "Session ended" in text and code == 0, f"exit={code}")
    check("sign-off reports duration and a next step", "Next:" in text and "Come back any time" in text)
    check("no traceback", "Traceback" not in out)

    # --- the dashboard's device/app numbers must actually open something ------
    # They were advertised on the footer but ignored: run_menu only accepted its
    # own option keys, so every digit fell through as an unknown key.
    print("number keys")
    home = homes.append(make_home()) or homes[-1]
    # Typed input collects on the prompt line and Enter commits it, which is what
    # lets a screen hold more than nine numbered rows.
    out, code = _run(home, [b"1", b"\r", b"b", b"x"])
    text = clean(out)
    check("a device number, typed and entered, opens that device",
          "dashboard › device" in text and "❯ 1" in text)
    # The whole toolset is on one screen: every category is a heading, and every
    # action carries a number you can type.
    check("the device screen lists every category and its actions",
          all(label in text for label in ("SCREEN & INPUT", "APPS", "FILES",
                                          "DEVICE CONTROL", "DEV TOOLS",
                                          "CONFIGURE DEVICE"))           and "Mirror Screen & Control" in text and "Remove this device" in text)
    check("backing out returns and quits cleanly", "Session ended" in text and code == 0, f"exit={code}")

    out, code = _run(homes.append(make_home()) or homes[-1],
                     [b"\x1b[B", b"\r", b"b", b"x"])   # ↓ selects the app row
    text = clean(out)
    check("the down arrow moves the highlight to the next row",
          "dashboard › app" in text and code == 0, f"exit={code}")

    # --- Ctrl+C is an exit, not a swallowed keypress ----------------------------
    print("interrupt handling")
    home = homes.append(make_home()) or homes[-1]
    out, code = _run(home, [b"\x03"])
    text = clean(out)
    check("ctrl+c prints the interrupted sign-off",
          "Session interrupted" in text and "nothing was left running" in text, f"exit={code}")
    check("ctrl+c exits 130", code == 130, f"exit={code}")
    check("ctrl+c leaves no traceback", "Traceback" not in out)

    # --- first run: guidance instead of invented devices ------------------------
    print("first run")
    home = homes.append(make_home(configured=False)) or homes[-1]
    out, code = _run(home, [b"x"])
    text = clean(out)
    check("first-run panel appears", "First run" in text and "Welcome to Fenox" in text)
    check("empty config is reported honestly", "0 devices" in text and "0 apps" in text)
    check("points at fenox init", "run fenox init" in text)
    check("the guidance stays until it is set up, and quit exits 0",
          "Session ended" in text and code == 0, f"exit={code}")

    # --- no terminal input at all ----------------------------------------------
    print("end of input")
    history = json.dumps({"demo:myphone:run": {
        "app": "demo", "device": "myphone", "action": "run", "ok": True,
        "ts": (datetime.datetime.now() + datetime.timedelta(seconds=30)).isoformat(timespec="seconds")}})
    home = homes.append(make_home(history=history)) or homes[-1]
    out, code = _run(home, [], tty=False)      # no keys: it only has to reach EOF
    text = clean(out)
    check("sign-off still printed", "Session ended" in text and "Input ended." in text, f"exit={code}")
    check("exit 0 for closed input", code == 0, f"exit={code}")
    check("session deploys summarised", "1 action this session" in text and "demo" in text)
    check("no traceback", "Traceback" not in out)

    # --- shell helpers must not wait on adb ------------------------------------
    print("shell integration stays instant")
    home = homes.append(make_home()) or homes[-1]
    proc, elapsed = quick(home, ["--version"])
    check("--version prints the version", proc.stdout.strip() == "fenox 1.0.1", proc.stdout.strip())
    check("--version is instant", elapsed < 2.0, f"{elapsed:.2f}s")
    check("--version skips the splash", "Session" not in proc.stdout and "adb" not in proc.stdout.lower())
    proc, elapsed = quick(home, ["--generate-completions", "bash"])
    check("completions are instant and non-empty", elapsed < 2.0 and bool(proc.stdout.strip()), f"{elapsed:.2f}s")
    proc, _ = quick(home, ["doctor"])
    check("subcommands never print the interactive bookends",
          "Session ended" not in proc.stdout and "fenox v" not in proc.stdout)
finally:
    for home in homes:
        shutil.rmtree(home, ignore_errors=True)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
