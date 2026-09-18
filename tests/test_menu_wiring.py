#!/usr/bin/env python3
"""Every menu key must do what the menu says it does.

The dashboard menus hand a keypress to an action, and a key that is advertised but
wired to the wrong action (or to nothing) is invisible until a user finds it. This
test loads the real source, swaps the action layer for recorders and the input
layer for a script, then presses every key each screen offers and checks which
action ran.

It caught two classes of bug in the existing menus: `b` was advertised as "Read
clipboard" on the screen menu while `b` is also the back key (unreachable), and in
the expert keypad `e`/`g`/`h`/`d` were shadowed by the upper-case A–Z action map
(Edit, Toggle, Remove and Refresh could not be reached at all).
"""
import os
import pathlib
import shutil
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "fenox.py"

failures = []


def check(desc, ok, detail=""):
    info = f" ({detail})" if detail else ""
    if ok:
        print(f"  \033[32mok\033[0m   {desc}{info}")
    else:
        print(f"  \033[31mFAIL\033[0m {desc}{info}")
        failures.append(desc)


def load_module(home):
    """Run the CLI source as __main__, but stop short of starting the UI."""
    os.environ["HOME"] = home
    globals_ns = {"__name__": "__main__", "__file__": str(SRC)}
    argv = sys.argv
    out = sys.stdout
    sys.argv = ["fenox", "--generate-completions", "bash"]   # returns immediately
    sys.stdout = open(os.devnull, "w")
    try:
        exec(compile(SRC.read_text(), str(SRC), "exec"), globals_ns)  # noqa: S102
    finally:
        sys.stdout.close()
        sys.stdout = out
        sys.argv = argv
    return globals_ns


home = tempfile.mkdtemp(prefix="fenox-wiring-")
project = os.path.join(home, "demo")
os.makedirs(project, exist_ok=True)
with open(os.path.join(home, ".fenox.json"), "w") as f:
    f.write('{"apps": {"demo": {"path": "%s", "port": "4000", '
            '"api_local": "http://localhost:4000/api"}}, '
            '"devices": {"myphone": {"ip": "192.168.1.50", "model": "Pixel 7", "port": "5555"}}, '
            '"settings": {"remote_domain": "demo.test", "projects_dir": "%s"}}' % (project, project))

g = load_module(home)

# --- replace the action layer with recorders ---------------------------------
recorded = []
queue = []
offered = []


def recorder(name):
    def call(*args, **kwargs):
        recorded.append(name)
    return call


for key, value in list(g.items()):
    if callable(value) and (key.startswith("action_") or key.startswith("_action_")):
        g[key] = recorder(key)
g["_open_last_capture"] = recorder("_open_last_capture")


def stub(key, value):
    g[key] = value


stub("check_and_connect", lambda *a, **k: "TESTID")          # pretend the phone is up
stub("save_config", lambda *a, **k: None)
stub("_wait_any_key", lambda *a, **k: None)                  # no reading between actions
stub("resolve_package", lambda *a, **k: "com.demo.app")
stub("_device_summary", lambda *a, **k: "Pixel 7")
g["Prompt"].ask = lambda *a, **k: "demo"                     # picker prompts
g["Prompt"].ask = staticmethod(g["Prompt"].ask) if False else g["Prompt"].ask
g["Confirm"].ask = lambda *a, **k: False                     # never confirm destructive steps


def fake_run_menu(title, options=(), **kwargs):
    # Keep (key, label) pairs: a test needs to know what each row advertises.
    offered.append((title, [(raw[0], raw[1]) for raw in options]))
    return queue.pop(0) if queue else None                   # empty queue = "back"


real_run_menu = g["run_menu"]         # kept for the input-contract checks below
g["run_menu"] = fake_run_menu

# `flutter clean` runs through os.system and os.chdir; keep both harmless.
real_system, real_chdir = os.system, os.chdir
os.system = lambda cmd: (recorded.append("os.system"), 0)[1]
os.chdir = lambda path: None


def silently(fn, *args):
    """Run a screen with its rendering swallowed — only the checks should print."""
    out = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        fn(*args)
    finally:
        sys.stdout.close()
        sys.stdout = out


def exercise(screen, launcher, expected):
    """Press each advertised key once, then back; check what each one triggered."""
    del recorded[:], queue[:], offered[:]
    mapping = dict(expected)
    queue.extend(list(mapping) + [])                         # keys, then empty → back
    silently(launcher)
    keys_shown = [key for key, _ in (offered[-1][1] if offered else [])]
    check(f"{screen}: every advertised key is covered",
          set(keys_shown) == set(mapping), f"menu={keys_shown} tested={list(mapping)}")
    # A key may legitimately run more than one thing ("flutter clean + pub get").
    want = []
    for key in mapping:
        value = mapping[key]
        want.extend(value if isinstance(value, list) else [value])
    check(f"{screen}: each key ran the action it advertises",
          recorded == [name for name in want if name], f"ran {recorded}")


try:
    exercise("app menu", lambda: g["app_actions"]("demo"),
             [("1", "action_run"), ("2", "action_run"), ("3", "action_run"),
              ("4", "action_open"), ("5", "action_build"),
              ("6", ["os.system", "os.system"]),   # flutter clean + pub get
              ("7", "action_backend")])

    # --- the device screen: the whole toolset on one numbered list ------------
    # The six category sub-menus are gone, so what matters now is that every row
    # is numbered continuously, shows the label it declares, and runs exactly the
    # handler that label belongs to.
    del recorded[:], queue[:], offered[:]
    sections = g["_device_action_sections"]("myphone")
    declared = [(label, handler) for _, _, actions in sections
                for label, _needs_device, handler in actions]
    queue.extend(str(n) for n in range(1, len(declared) + 1))
    silently(g["device_actions"], "myphone")
    rows = offered[-1][1] if offered else []
    numbers = [key for key, _ in rows if key is not None]
    check("device screen: one row per action, numbered from 1 with no gaps",
          numbers == [str(n) for n in range(1, len(declared) + 1)],
          f"{len(numbers)} numbered rows for {len(declared)} actions")
    check("device screen: the list shows the labels it declares",
          [label for key, label in rows if key is not None] == [label for label, _ in declared])

    # Numbers 1..49 in reading order, which is the order (section, action) declares.
    # (The four configure entries sit last: they run no action of their own.)
    expected = [
        "action_messages", "action_calls", "action_contacts", "action_calendar",
        "action_mirror", "action_media", "action_media", "_action_wake", "_action_lock",
        "_action_type_text", "_action_tap_screen", "_action_swipe", "_action_key_combo",
        "_action_clipboard_copy", "_action_clipboard_read", "_action_open_url",
        "_open_last_capture",
        "action_open", "_action_list_apps", "_action_uninstall_app",
        "_action_clear_app_data", "_action_force_stop", "_action_app_info",
        "_action_install_apk_from_pc", "action_nuke",
        "_action_push_file", "_action_pull_file", "_action_browse_storage",
        "_action_reboot_menu", "_action_toggle_wifi", "_action_toggle_data",
        "_action_toggle_bluetooth", "_action_volume_control",
        "_action_brightness_control", "_action_interactive_shell",
        "_action_device_info_dashboard", "_action_battery_info", "_action_network_info",
        "_action_storage_info", "_action_running_processes",
        "_action_send_notification", "_action_read_notifications", "action_bind",
        "action_logs", "_action_health_monitor",
    ]
    check("device screen: each number ran the action it advertises",
          recorded == expected, f"ran {recorded}")
    check("device screen: the configure rows changed nothing on their own",
          len(expected) == len(declared) - 4 and "myphone" in g["DEVICES"],
          f"{len(expected)} actions vs {len(declared)} rows")
    labels = [label for label, _ in declared]
    check("device screen: the phone section carries all four readers",
          any("Read messages" in label for label in labels)
          and any("call log" in label for label in labels)
          and any("Read contacts" in label for label in labels)
          and any("Read the calendar" in label for label in labels),
          f"{len(declared)} actions")

    # --- the input contract: arrows move the highlight, Enter commits ----------
    # Enter used to be reported by the key reader and then ignored by every menu.
    import io

    class FakeTTY(io.StringIO):
        def isatty(self): return True
        def fileno(self): return 0

    real_stdin = sys.stdin
    sys.stdin = FakeTTY()
    try:
        keys = []
        g["_read_key"] = lambda timeout=None: keys.pop(0) if keys else None

        def call_menu(*args, **kwargs):
            out, sys.stdout = sys.stdout, open(os.devnull, "w")
            try:
                return real_run_menu(*args, **kwargs)
            finally:
                sys.stdout.close()
                sys.stdout = out

        rows = [("1", "One"), ("2", "Two"), ("3", "Three")]

        def press(sequence, options=None, **kwargs):
            keys[:] = list(sequence)
            return call_menu("Title", options or rows, **kwargs)

        check("Enter opens the highlighted row", press(["enter"]) == "1")
        check("down then Enter opens the second row", press(["down", "enter"]) == "2")
        check("up wraps to the last row", press(["up", "enter"]) == "3")
        check("a key typed then Enter opens that row", press(["3", "enter"]) == "3")
        check("a key with no Enter never fires it", press(["3"]) is None)
        check("b and Esc go back", press(["b"]) is None and press(["esc"]) is None)
        check("live (refreshing) menus take the same keys",
              press(["down", "enter"], interval=0.01) == "2")
        carry = {}
        press(["down"], state=carry)
        check("a caller-owned cursor is remembered", carry.get("cursor") == 1, f"{carry}")

        # Numbers longer than one digit are the reason the input line exists: they
        # have to be able to build up, which a bare keypress cannot do.
        two_digit = [("1", "One"), ("12", "Twelve")]
        check("a two-digit number builds up and opens its row",
              press(["1", "2", "enter"], options=two_digit) == "12")
        check("Backspace edits what was typed",
              press(["9", "backspace", "3", "enter"]) == "3")
        typed = {}
        press(["z", "enter"], state=typed)
        check("input that names no row keeps the screen open",
              typed.get("typed") == "z", f"{typed}")
        cleared = {}
        check("Esc clears the input before it goes back",
              press(["4", "esc", "enter"], state=cleared) == "1", f"{cleared}")
        check("arrows drop the typed input",
              (lambda s: (press(["1", "down", "enter"], state=s), s)[1])({}).get("typed") == "",
              "typing then arrowing must not leave a stale number behind")
    finally:
        sys.stdin = real_stdin
finally:
    os.system, os.chdir = real_system, real_chdir
    shutil.rmtree(home, ignore_errors=True)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
