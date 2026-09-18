#!/usr/bin/env python3
import os, subprocess, sys, json, argparse, shutil, datetime, time, secrets, string, re, signal, shlex
from pathlib import Path
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich.cells import cell_len

console = Console()
CONFIG_PATH = os.path.expanduser("~/.fenox.json")
HISTORY_PATH = os.path.expanduser("~/.fenox_history.json")

# --- Shared ADB server (Windows side) ---------------------------------------
# WSL mirrored networking shares the port space with Windows. The Linux adb
# server cannot see USB devices, so fenox routes ALL adb traffic to the
# Windows adb.exe server on a dedicated port (5038). The Linux adb server
# keeps the default port 5037 so stray `adb` calls never start a competing
# server there. USB debugging works because only Windows can see USB.
ADB_SERVER_PORT = 5038
FENOX_VERSION = "1.0.1"
FENOX_REPO = "onefennox/fenox"
# Content providers whose data the adb `shell` user may read on a stock device.
SMS_URI = "content://sms"
SMS_INBOX_URI = "content://sms/inbox"
SMS_THREADS_URI = "content://sms/conversations"
CONTACT_PHONES_URI = "content://com.android.contacts/data/phones"
CALL_LOG_URI = "content://call_log/calls"
CALENDAR_URI = "content://com.android.calendar/calendars"
CALENDAR_EVENTS_URI = "content://com.android.calendar/events"
CALENDAR_INSTANCES_URI = "content://com.android.calendar/instances/when/{start}/{end}"
# CallLog.Calls type codes as the provider stores them, and the words they mean.
# 4 is a voicemail, 7 a call that was answered somewhere else.
CALL_KINDS = {"1": "incoming", "2": "outgoing", "3": "missed", "4": "voicemail",
              "5": "rejected", "6": "blocked", "7": "answered elsewhere"}
CALL_KIND_KEYS = {"incoming": "1", "outgoing": "2", "missed": "3", "voicemail": "4",
                  "rejected": "5", "blocked": "6", "answered elsewhere": "7"}
# Extended one resource at a time; each has to be read from a real device before
# being offered, because the providers differ between ROMs.
PHONE_RESOURCES = ("messages", "calls", "contacts", "calendar")
KNOWN_COMMANDS = {"run", "bind", "connect", "rename", "logs", "nuke", "mirror", "screenshot", "record", "build", "doctor", "sync", "discover", "add-app", "scan", "backend", "hot", "install", "open", "pair", "pair-qr", "devices", "profile", "watch", "update", "groups", "init", "uninstall", "phone"}
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"
IS_WSL = os.path.exists("/proc/version") and ("microsoft" in open("/proc/version").read().lower() or bool(os.environ.get("WSL_DISTRO_NAME")))

def _win_user():
    """Best-effort Windows username (WSL only)."""
    if not IS_WSL:
        return None
    try:
        for cand in Path("/mnt/c/Users").iterdir():
            if cand.name not in ("Public", "Default", "Default User", "All Users") and not cand.name.startswith("desktop.ini") and cand.is_dir() and (cand / "NTUSER.DAT").exists():
                return cand.name
    except Exception:
        pass
    try:
        out = subprocess.run(["/mnt/c/Windows/System32/cmd.exe", "/c", "echo %USERNAME%"], capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL).stdout.strip()
        if out and out != "%USERNAME%":
            return out
    except Exception:
        pass
    return None

_WIN_USER = _win_user()

def _find_windows_adb():
    """Locate Windows adb.exe in the usual places (WSL only)."""
    if not IS_WSL:
        return None
    candidates = ["/mnt/c/platform-tools/adb.exe"]
    user = _WIN_USER
    if user:
        candidates += [f"/mnt/c/Users/{user}/AppData/Local/Android/Sdk/platform-tools/adb.exe",
                       f"/mnt/c/Users/{user}/Android/Sdk/platform-tools/adb.exe"]
    candidates += ["/mnt/c/Android/platform-tools/adb.exe", "/mnt/c/tools/platform-tools/adb.exe"]
    for c in candidates:
        if os.path.exists(c):
            return c
    try:
        out = subprocess.run(["/mnt/c/Windows/System32/cmd.exe", "/c", "where adb"], capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL).stdout.strip().splitlines()
        if out:
            winpath = out[-1].strip()
            drive, rest = winpath[0].lower(), winpath[2:].replace("\\", "/")
            p = f"/mnt/{drive}{rest}"
            if os.path.exists(p):
                return p
    except Exception:
        pass
    return None

ADB_EXE = _find_windows_adb() or "/mnt/c/platform-tools/adb.exe"

def _fenox_dir():
    """Portable output root: Windows Desktop via WSL mount, else ~/Fenox."""
    if IS_WSL and _WIN_USER:
        p = f"/mnt/c/Users/{_WIN_USER}/Desktop/Fenox"
        if os.path.isdir("/mnt/c/Users"):
            return p
    return os.path.expanduser("~/Fenox")

def _win_fenox_dir():
    if IS_WSL and _WIN_USER:
        return rf"C:\Users\{_WIN_USER}\Desktop\Fenox"
    return _fenox_dir()

_FENOX_DIR_ROOT = _fenox_dir()
_WIN_FENOX_DIR_ROOT = _win_fenox_dir()

# Route this process AND every child (flutter, scrcpy, adb) to the shared
# Windows adb server so they all see USB + wireless devices.
os.environ["ANDROID_ADB_SERVER_PORT"] = str(ADB_SERVER_PORT)

def ensure_shared_adb_server():
    """Make sure the Windows adb server is listening on ADB_SERVER_PORT (idempotent, silent)."""
    try:
        probe = subprocess.run(
            [ADB_EXE, "-P", str(ADB_SERVER_PORT), "devices"],
            capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL,
        )
        if probe.returncode == 0 and "List of devices" in probe.stdout:
            return
    except Exception:
        pass
    try:
        # Under mirrored networking, a Linux adb server may have squatted the
        # shared port (it can't see USB). Evict it so Windows adb can bind.
        squat = run_cmd("ss -tlnp 2>/dev/null")
        for line in squat.splitlines():
            if f":{ADB_SERVER_PORT} " in line and "adb" in line:
                pid_match = re.search(r"pid=(\d+)", line)
                if pid_match:
                    run_cmd(f"kill {pid_match.group(1)} 2>/dev/null")
                    time.sleep(1)
                break
    except Exception:
        pass
    try:
        subprocess.run(
            ["/mnt/c/Windows/System32/taskkill.exe", "/IM", "adb.exe", "/F"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
        )
        time.sleep(1)
        subprocess.Popen(
            [ADB_EXE, "-P", str(ADB_SERVER_PORT), "start-server"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
    except Exception:
        pass

# --- Output directories (Windows Desktop via WSL mount, portable) ---
FENOX_DIR = _FENOX_DIR_ROOT
SHOTS_DIR = os.path.join(FENOX_DIR, "Screenshots")
RECS_DIR = os.path.join(FENOX_DIR, "Recordings")
LOGS_DIR = os.path.join(FENOX_DIR, "Logs")
APKS_DIR = os.path.join(FENOX_DIR, "APKs")
# Windows path representation (for PowerShell clipboard / opening in Windows apps)
WIN_FENOX_DIR = _WIN_FENOX_DIR_ROOT
WIN_SHOTS_DIR = WIN_FENOX_DIR + r"\Screenshots"
WIN_RECS_DIR = WIN_FENOX_DIR + r"\Recordings"
WIN_LOGS_DIR = WIN_FENOX_DIR + r"\Logs"
WIN_APKS_DIR = WIN_FENOX_DIR + r"\APKs"

OUTPUT_DIRS = {
    "screenshot": (SHOTS_DIR, WIN_SHOTS_DIR),
    "record": (RECS_DIR, WIN_RECS_DIR),
    "logs": (LOGS_DIR, WIN_LOGS_DIR),
    "apk": (APKS_DIR, WIN_APKS_DIR),
}

def ensure_output_dirs():
    for media_type, (wsl_dir, win_dir) in OUTPUT_DIRS.items():
        os.makedirs(wsl_dir, exist_ok=True)

# A fresh install starts deliberately empty. Shipping sample apps and devices here
# meant every new user was handed aliases (myapp-myphone, myapp-emulator, ...) that
# pointed at projects and devices which do not exist on their machine. `fenox init`
# collects the settings, `fenox scan`/`doctor` discover the rest.
DEFAULT_CONFIG = {
    "apps": {},
    "devices": {},
    "settings": {
        "remote_domain": "",
        "projects_dir": "",
    },
}

def merge_defaults(base, incoming):
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = merge_defaults(merged[key], value)
            else:
                merged[key] = value
        return merged
    return incoming

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, 'r') as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        backup = f"{CONFIG_PATH}.corrupt-{int(time.time())}"
        try: shutil.copy(CONFIG_PATH, backup)
        except OSError: pass
        console.print(f"[red]⚠️ Config file is corrupted ({e}). Backed up to {backup} and reset to defaults.[/red]")
        with open(CONFIG_PATH, 'w') as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    return merge_defaults(DEFAULT_CONFIG, loaded)

def save_config():
    config["devices"] = DEVICES
    config["apps"] = APPS
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, 'w') as f: json.dump(config, f, indent=4)
    os.replace(tmp_path, CONFIG_PATH)  # atomic write — no half-written configs
    # Rolling backups (keep the last 5)
    try:
        backup_dir = os.path.expanduser("~/.fenox-backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(CONFIG_PATH, os.path.join(backup_dir, f"fenox.json.{ts}"))
        backups = sorted(Path(backup_dir).glob("fenox.json.*"))
        for old in backups[:-5]:
            old.unlink()
    except OSError:
        pass

def log_history(app_key, dev_key, action, ok=True):
    """Record a run/build event so the dashboard can show 'last run'."""
    try:
        history = {}
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, 'r') as f: history = json.load(f)
        key = f"{app_key}:{dev_key or 'all'}:{action}"
        history[key] = {
            "app": app_key, "device": dev_key or "all", "action": action,
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "ok": bool(ok),
        }
        with open(HISTORY_PATH, 'w') as f: json.dump(history, f, indent=2)
    except OSError:
        pass

def get_last_run(app_key, dev_key=None, action=None):
    try:
        if not os.path.exists(HISTORY_PATH): return None
        with open(HISTORY_PATH, 'r') as f: history = json.load(f)
        candidates = [v for v in history.values()
                      if v.get("app") == app_key
                      and (dev_key is None or v.get("device") == dev_key)
                      and (action is None or v.get("action") == action)]
        if not candidates: return None
        return max(candidates, key=lambda v: v.get("ts", ""))
    except Exception:
        return None

def resolve_package(app_key):
    """Auto-resolve the Android package name from the project (no more manual prompting)."""
    if app_key not in APPS: return None
    app_data = APPS[app_key]
    if app_data.get("package"):
        return app_data["package"]
    path = os.path.expanduser(app_data.get("path", ""))
    # Try applicationId / namespace in gradle files (modern Flutter projects)
    for gradle in ["android/app/build.gradle", "android/app/build.gradle.kts"]:
        gpath = os.path.join(path, gradle)
        if os.path.exists(gpath):
            try:
                content = open(gpath, encoding="utf-8", errors="ignore").read()
                m = re.search(r'applicationId\s+["\']([^"\']+)["\']', content)
                if not m:
                    m = re.search(r'namespace\s+["\']([^"\']+)["\']', content)
                if m:
                    app_data["package"] = m.group(1)
                    return m.group(1)
            except OSError:
                pass
    # Fallback: package attribute declared in AndroidManifest.xml
    manifest = os.path.join(path, "android", "app", "src", "main", "AndroidManifest.xml")
    if os.path.exists(manifest):
        try:
            content = open(manifest, encoding="utf-8", errors="ignore").read()
            m = re.search(r'package="([^"]+)"', content)
            if m:
                app_data["package"] = m.group(1)
                return m.group(1)
        except OSError:
            pass
    return None

config = load_config()
APPS = config.get("apps", {})
DEVICES = config.get("devices", {})

def get_projects_dir():
    """Where this machine keeps its Flutter projects.

    Returns the directory chosen during `fenox init`, or the first conventional
    location that actually exists — never a path that is merely assumed.
    """
    raw = str(config.get("settings", {}).get("projects_dir") or "").strip()
    if raw:
        return os.path.expanduser(raw)
    for candidate in ("~/Projects", "~/projects", "~/code", "~/src", "~/dev"):
        path = os.path.expanduser(candidate)
        if os.path.isdir(path):
            return path
    return os.path.expanduser("~/Projects")

def _ask(prompt, default=""):
    """Prompt for input only when a human is attached; otherwise take the default."""
    if not sys.stdin.isatty():
        return default
    try:
        return Prompt.ask(prompt, default=default)
    except (EOFError, KeyboardInterrupt):
        return default

def _confirm(prompt, default=True):
    """Confirm only when a human is attached; non-interactive runs answer 'no'."""
    if not sys.stdin.isatty():
        return False
    try:
        return Confirm.ask(prompt, default=default)
    except (EOFError, KeyboardInterrupt):
        return default

def run_cmd(cmd, timeout=None):
    # stdin is /dev/null on purpose: these are captured, non-interactive commands,
    # and a child that reads the terminal would swallow the user's next keypress.
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL).stdout.strip()
    except Exception:
        return ""

def get_connected_device_ids():
    raw_ids = [line.strip().split()[0] for line in run_cmd("timeout 5 adb devices").splitlines() if line.strip() and "device" in line and not line.strip().startswith("List")]
    # Filter out mDNS hostname duplicates when IP-based already exists
    ip_based = {d for d in raw_ids if d.count('.') == 3 and ':' in d}
    filtered = []
    for d_id in raw_ids:
        if '_adb-tls-connect' in d_id:
            # Skip mDNS name if its IP:port is already connected
            if any(d_id.split('.')[0] in ip_id for ip_id in ip_based):
                continue
        filtered.append(d_id)
    return filtered

def is_device_enabled(dev_info):
    return not dev_info.get("disabled", False)

def try_connect(target_ip, port):
    result = run_cmd(f"timeout 8 adb connect {target_ip}:{port}")
    connected = any(token in result.lower() for token in ["connected", "already connected"])
    return connected, result

def _mdns_port_for(target_ip):
    """Find the current wireless-debugging port via mDNS for a given IP."""
    mdns_output = run_cmd("adb mdns services 2>/dev/null")
    for line in mdns_output.splitlines():
        if target_ip in line and "_adb-tls-connect" in line:
            parts = line.split()
            if len(parts) >= 3:
                addr = parts[2]
                if ":" in addr:
                    return addr.split(":")[1]
    return None

def _remember_port(dev_key, port):
    """Save the working port and keep a short history of recent ports."""
    if not port: return
    dev_info = DEVICES[dev_key]
    history = dev_info.get("port_history", [])
    history = [p for p in history if str(p) != str(port)]
    history.insert(0, str(port))
    dev_info["port_history"] = history[:5]
    dev_info["port"] = str(port)

# --- Parallel device telemetry (thread pool — 3-5x faster dashboards/doctor) ---
from concurrent.futures import ThreadPoolExecutor

# --- Device telemetry (cached briefly so the dashboard is instant) ---
TELEMETRY_CACHE = {}
TELEMETRY_TTL = 15

def get_device_telemetry_parallel(dev_ids):
    """Fetch telemetry for many devices concurrently."""
    if not dev_ids:
        return
    with ThreadPoolExecutor(max_workers=min(8, max(2, len(dev_ids)))) as pool:
        list(pool.map(lambda d: get_device_telemetry(d), dev_ids))

def get_device_telemetry(dev_id, force=False):
    now = time.time()
    cached = TELEMETRY_CACHE.get(dev_id)
    if cached and not force and (now - cached["ts"]) < TELEMETRY_TTL:
        return cached["data"]
    data = {"battery": "?", "charging": None, "screen": "?", "android": "?", "storage": "?", "app": "?", "model": "?"}
    def sh(cmd):
        return run_cmd(f"timeout 5 adb -s {dev_id} {cmd}")
    try:
        for line in sh("shell dumpsys battery").splitlines():
            line = line.strip()
            if line.startswith("level:"):
                data["battery"] = line.split(":", 1)[1].strip()
            elif line.startswith("status:"):
                data["charging"] = line.split(":", 1)[1].strip() == "2"
        for line in sh("shell dumpsys power").splitlines():
            if "mWakefulness=" in line:
                val = line.split("mWakefulness=")[1].split(" ")[0].strip()
                data["screen"] = "On" if val == "Awake" else "Off"
                break
        data["android"] = sh("shell getprop ro.build.version.release").strip() or "?"
        for line in sh("shell df /data 2>/dev/null").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] != "Filesystem":
                data["storage"] = parts[4]
                break
        for line in sh("shell dumpsys activity activities 2>/dev/null").splitlines():
            if "topResumedActivity" in line or "mFocusedApp" in line:
                comp = re.search(r'ActivityRecord\{[^}]*\s+[^/]+/([^}\s]+)', line)
                if comp:
                    data["app"] = comp.group(1).split(".")[-1]
                    break
        data["model"] = sh("shell getprop ro.product.model").strip() or "?"
    except Exception:
        pass
    TELEMETRY_CACHE[dev_id] = {"ts": now, "data": data}
    return data

def check_and_connect(dev_key, interactive=False):
    if dev_key not in DEVICES: return None
    dev_info = DEVICES[dev_key]
    if not is_device_enabled(dev_info):
        return None
    
    # --- Emulator handling ---
    if dev_info.get("type") == "emulator":
        for d_id in get_connected_device_ids():
            if d_id.startswith("emulator-"):
                return d_id
        if interactive:
            console.print(f"[yellow]⚠️ Emulator '{dev_key}' not found. Make sure your Android emulator is running and visible in 'adb devices'.[/yellow]")
        return None
    
    # --- USB device handling (shared Windows adb server sees USB) ---
    if dev_info.get("type") == "usb":
        serial = str(dev_info.get("serial", "") or "")
        for d_id in get_connected_device_ids():
            if d_id.startswith("emulator-") or ":" in d_id:
                continue  # skip emulators and ip:port wireless ids
            if serial and d_id != serial:
                continue
            return d_id
        if interactive:
            console.print(f"[yellow]⚠️ USB device '{dev_key}' not detected. Plug it in and accept the debugging prompt on the phone.[/yellow]")
        return None
    
    # --- Wireless device handling ---
    target_ip = dev_info["ip"]
    target_port = dev_info.get("port")  # last used port only — no hardcoded default
    
    def _is_connected():
        for d_id in get_connected_device_ids():
            if target_ip in d_id or dev_info.get("model", "") in run_cmd(f"timeout 5 adb -s {d_id} shell getprop ro.product.model"):
                return d_id
        return None

    # First check if already connected
    d_id = _is_connected()
    if d_id: return d_id

    # mDNS-first: if the phone advertises its current port, use it directly
    mdns_port = _mdns_port_for(target_ip)
    if mdns_port and str(mdns_port) != str(target_port):
        connected, _ = try_connect(target_ip, mdns_port)
        d_id = _is_connected()
        if connected and d_id:
            _remember_port(dev_key, mdns_port)
            save_config()
            console.print(f"[green]✅ Connected via mDNS on port {mdns_port}![/green]")
            return d_id

    # Try the last used port + recent history before asking the user
    candidates = []
    if target_port: candidates.append(str(target_port))
    for p in dev_info.get("port_history", []):
        if str(p) not in candidates:
            candidates.append(str(p))
    tried = 0
    for p in candidates:
        connected, _ = try_connect(target_ip, p)
        d_id = _is_connected()
        if connected and d_id:
            if str(p) != str(target_port):
                _remember_port(dev_key, p)
                save_config()
            return d_id
        tried += 1
    # Non-interactive (doctor/sync/blast silent pass): never prompt, just report offline
    if not interactive:
        return None
    if tried:
        console.print(f"[yellow]⚠️ {dev_key.upper()} did not respond on {tried} recent port(s).[/yellow]")

    # Request a working port from the user
    console.print(f"\n[yellow]📱 {dev_key.upper()} ({target_ip}) is not connected.[/yellow]")
    if mdns_port:
        console.print(f"[green]📡 mDNS detected port: {mdns_port}[/green]")
    elif target_port:
        console.print(f"[dim]Saved port: {target_port} (may be stale)[/dim]")
    else:
        console.print("[dim]No saved port for this device.[/dim]")
    
    default_port = mdns_port or (str(target_port) if target_port else "")
    port = Prompt.ask(
        f"Enter the current wireless debugging port for {dev_key.upper()} at {target_ip}",
        default=default_port,
    )
    console.print(f"[cyan]Connecting to {target_ip}:{port}...[/cyan]")
    connected, result = try_connect(target_ip, port)
    d_id = _is_connected()
    if d_id:
        _remember_port(dev_key, port)
        save_config()
        console.print(f"[green]✅ Connected! Port {port} saved for {dev_key.upper()}.[/green]")
        return d_id
    console.print(f"[red]❌ Failed to connect to {dev_key.upper()} on port {port}.[/red]")
    console.print(f"[yellow]Result: {result}[/yellow]")
        
    # Explain why and offer pairing
    console.print("""
[yellow]⚠️  Common reasons for connection failure:[/yellow]
  • Device needs to be PAIRED first (use 'adb pair' once per WiFi network)
  • The connection port changed (re-enter the new port)
  • Phone screen is locked or Wireless Debugging was turned off

[cyan]💡 You can pair using:[/cyan]
  1. 📸 [bold]fenox pair-qr[/bold] — QR code method (recommended)
  2. 🔢 [bold]fenox pair[/bold] — Manual pairing code
""")
    pair_choice = Confirm.ask("[yellow]Would you like to pair the device now?[/yellow]")
    if pair_choice:
        method = Prompt.ask("Choose method", choices=["qr", "manual"], default="qr")
        if method == "qr":
            # Launch QR pairing inline
            console.print(f"\n[cyan]Make sure your phone shows a QR code:[/cyan]")
            console.print(f"1. On phone: [bold]Developer Options -> Wireless Debugging[/bold]")
            console.print(f"2. Tap [bold]'Pair device with QR code'[/bold]")
            qr_img = Prompt.ask("Path to QR code screenshot (or press Enter to enter details manually)")
            pair_port = ""
            pair_code = ""
            if qr_img:
                qr_path = os.path.expanduser(qr_img)
                if os.path.exists(qr_path):
                    if shutil.which("zbarimg"):
                        qr_data = run_cmd(f"zbarimg --raw -q '{qr_path}' 2>/dev/null")
                        if qr_data:
                            m = re.search(r'S:[\d\.]+:(\d+);P:([^;]+)', qr_data)
                            if m:
                                pair_port, pair_code = m.groups()
                                console.print(f"[green]✅ QR decoded! Pairing port: {pair_port}[/green]")
            if not pair_port:
                pair_port = Prompt.ask("Enter the PAIRING port shown on your phone (e.g. 43215)")
            if not pair_code:
                pair_code = Prompt.ask("Enter the 6-digit pairing code")
        else:
            console.print(f"\n[cyan]Make sure your phone shows a 6-digit pairing code.[/cyan]")
            console.print(f"1. On phone: [bold]Developer Options -> Wireless Debugging[/bold]")
            console.print(f"2. Tap [bold]'Pair device with pairing code'[/bold]")
            pair_port = Prompt.ask("Enter the PAIRING port shown on your phone (e.g. 43215)")
            pair_code = Prompt.ask("Enter the 6-digit pairing code")
        
        console.print(f"\n[yellow]Pairing with {target_ip}:{pair_port}...[/yellow]")
        pair_result = run_cmd(f"adb pair {target_ip}:{pair_port} {pair_code}")
        console.print(pair_result)
        
        if "Successfully paired" in pair_result:
            console.print("[green]✅ Paired! Now connecting...[/green]")
            connected, result = try_connect(target_ip, port)
            d_id = _is_connected()
            if d_id:
                _remember_port(dev_key, port)
                save_config()
                console.print(f"[green]✅ Connected! Port {port} saved for {dev_key.upper()}.[/green]")
                return d_id
            console.print(f"[red]❌ Still failed after pairing. Make sure you're using the correct CONNECTION port (the one shown on the main Wireless Debugging screen).[/red]")
        else:
            console.print("[red]❌ Pairing failed. Make sure the code and port are correct.[/red]")
    return None

# --- Wireless Pairing Wizard (Manual Code) ---
def action_pair():
    console.print(Panel.fit("[bold cyan]📶 Android 11+ Wireless Pairing (Manual)[/bold cyan]", border_style="cyan"))
    console.print("1. Go to phone [bold]Developer Options -> Wireless Debugging[/bold]")
    console.print("2. Tap [bold]'Pair device with pairing code'[/bold]\n")
    
    ip = Prompt.ask("Enter Device IP")
    port = Prompt.ask("Enter PAIRING Port (e.g. 43215)")
    code = Prompt.ask("Enter 6-digit Wi-Fi pairing code")
    
    console.print(f"\n[yellow]Pairing with {ip}:{port}...[/yellow]")
    result = run_cmd(f"adb pair {ip}:{port} {code}")
    console.print(result)
    
    if "Successfully paired" in result:
        console.print("\n[green]✅ Pair successful![/green]")
        conn_port = Prompt.ask("Now, enter the standard Connection Port (shown on main Wireless Debugging screen)")
        run_cmd(f"adb connect {ip}:{conn_port}")
        
        dev_name = Prompt.ask("Enter a short name to save this device (e.g. s24)")
        model = run_cmd(f"adb -s {ip}:{conn_port} shell getprop ro.product.model")
        DEVICES[dev_name] = {"ip": ip, "model": model, "port": conn_port}
        save_config()
        console.print(f"[green]✅ Device {dev_name} saved![/green]")
    else: console.print("[red]❌ Pairing failed.[/red]")

# --- QR Code Pairing (PC shows QR, phone scans) ---
def get_local_ip():
    """Get the local IP address of this machine."""
    ip = run_cmd("ip route get 1 2>/dev/null | awk '{print $(NF-2); exit}'")
    if ip: return ip
    ip = run_cmd("hostname -I 2>/dev/null | awk '{print $1}'")
    if ip: return ip
    return run_cmd("ifconfig 2>/dev/null | grep 'inet ' | grep -v 127.0.0.1 | awk '{print $2}' | head -1")

def action_pair_qr():
    console.print(Panel.fit("[bold cyan]📸 PC Shows QR → Phone Scans It[/bold cyan]", border_style="cyan"))
    
    # 1. Get PC's local IP
    pc_ip = get_local_ip()
    if not pc_ip:
        console.print("[red]❌ Could not determine your PC's IP address.[/red]")
        console.print("[yellow]Make sure you're connected to a network.[/yellow]")
        return
    
    # 2. Choose a port and generate a pairing password
    adb_port = 3737
    password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    
    # 3. Ensure the shared ADB server is up (do NOT kill it — USB devices live there)
    console.print(f"[yellow]Starting ADB network listener on port {adb_port}...[/yellow]")
    ensure_shared_adb_server()
    
    # Start ADB server in network mode
    proc = subprocess.Popen(
        ["adb", "-a", "-P", str(adb_port), "nodaemon", "server"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    console.print(f"[green]✅ ADB listening on {pc_ip}:{adb_port}[/green]\n")
    
    # 4. Generate the QR code data
    # Format: WIFI:T:ADB;S:<host>:<port>;P:<password>;;
    qr_data = f"WIFI:T:ADB;S:{pc_ip}:{adb_port};P:{password};;"
    
    # 5. Display the QR code in terminal
    console.print("[bold yellow]📱 Scan this QR code with your phone:[/bold yellow]")
    console.print("  [dim]Phone: Settings → Developer Options → Wireless Debugging[/dim]")
    console.print("  [dim]Then tap [bold]'Pair device with QR code'[/bold] and scan this QR code.\n[/dim]")
    
    os.system(f'qrencode -t ANSIUTF8 "{qr_data}"')
    
    console.print(f"\n[cyan]⏳ Waiting for your phone to connect... (Ctrl+C to cancel)[/cyan]")
    console.print(f"[dim]QR data: {qr_data}[/dim]")
    
    # 6. Wait for the device to appear
    known_ids = set(get_connected_device_ids())
    device_id = None
    for _ in range(60):  # Wait up to 60 seconds
        time.sleep(1)
        current_ids = set(get_connected_device_ids())
        new_ids = current_ids - known_ids
        for d_id in new_ids:
            if not d_id.startswith("emulator-"):
                device_id = d_id
                break
        if device_id:
            break
    
    # Restore normal ADB server
    proc.kill()
    time.sleep(0.5)
    ensure_shared_adb_server()
    
    if device_id and device_id != pc_ip:
        console.print(f"\n[green]✅ Device connected: {device_id}[/green]")
        
        # Check if we already know this device
        already_known = False
        for key, info in DEVICES.items():
            if info.get("ip", "") in device_id or device_id in str(info):
                already_known = True
                console.print(f"[green]Device '{key}' is already in your config![/green]")
                break
        
        if not already_known:
            # Extract IP from device_id
            if ":" in device_id:
                dev_ip = device_id.split(":")[0]
            else:
                dev_ip = device_id
            
            model = run_cmd(f"adb -s {device_id} shell getprop ro.product.model")
            dev_name = Prompt.ask("Enter a short name for this device", default="newphone")
            DEVICES[dev_name] = {"ip": dev_ip, "model": model, "port": str(adb_port)}
            save_config()
            console.print(f"[green]✅ Device '{dev_name}' saved![/green]")
    else:
        console.print("\n[yellow]⚠️ No new device detected within 60 seconds.[/yellow]")
        console.print(f"""
[yellow]Tips:[/yellow]
  1. Make sure your phone is on the [bold]same WiFi network[/bold] as this PC
  2. On phone: [bold]Developer Options → Wireless Debugging → Pair with QR code[/bold]
  3. Scan the QR code above with your phone's camera
  4. If scanning doesn't work, use [bold]fenox pair[/bold] instead (manual code)

[cyan]Your PC IP: {pc_ip}
ADB Port: {adb_port}
Password: {password}[/cyan]
""")

# --- Scrcpy Mirroring ---
# Android 14 already broke some of scrcpy 1.x's shell tricks, and Android 15
# removed SurfaceControl.createDisplay entirely, which kills the video encoder
# on the 1.25 that Ubuntu 24.04 ships. Kept in one place so the version floor is
# checkable rather than folklore.
SCRCPY_MIN_VERSION = (2, 4)
SCRCPY_TOO_OLD = (
    'scrcpy {found} is too old for Android {android} — its screen encoder uses '
    'calls Android has removed.\n'
    'Mirroring needs scrcpy {minv}.0 or newer. Install the official build next to this '
    'app (no sudo needed):\n\n'
    '    mkdir -p ~/.local/opt ~/.local/bin\n'
    '    wget -O /tmp/scrcpy.tar.gz '
    'https://github.com/Genymobile/scrcpy/releases/download/v{latest}/scrcpy-linux-x86_64-v{latest}.tar.gz\n'
    '    tar -xzf /tmp/scrcpy.tar.gz -C ~/.local/opt\n'
    '    ln -sf ~/.local/opt/scrcpy-linux-x86_64-v{latest}/scrcpy ~/.local/bin/scrcpy\n\n'
    'Then start a new terminal so ~/.local/bin is picked up.')


def scrcpy_version(binpath):
    """(major, minor) of a scrcpy binary, or None when it will not say."""
    try:
        probe = subprocess.run([binpath, "--version"], capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"scrcpy\s+v?(\d+)\.(\d+)", probe.stdout + probe.stderr)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _android_release(dev_id):
    """The device's Android version, for explaining version mismatches."""
    try:
        probe = subprocess.run(
            ["adb", "-P", str(ADB_SERVER_PORT), "-s", dev_id,
             "shell", "getprop", "ro.build.version.release"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "?"
    return probe.stdout.strip() or "?"


def _scrcpy_log_file(dev_id):
    """A per-run log path, the same layout the screenshots and recordings use."""
    dev_sub = os.path.join(LOGS_DIR, re.sub(r"[^\w.-]", "_", str(dev_id)))
    try:
        os.makedirs(dev_sub, exist_ok=True)
    except OSError:
        dev_sub = LOGS_DIR
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(dev_sub, f"mirror_{stamp}.log")


def action_mirror(dev_key):
    """Mirror the phone with scrcpy, and say so when it does not come up.

    scrcpy's output used to be discarded, so a failed launch read as a silent
    no-op: the user picked Mirror, nothing appeared, and the tool said nothing.
    It now keeps the window's output in a log file and reports when the mirror
    is not up after a few seconds, with the log to look at.
    """
    scrcpy_bin = shutil.which("scrcpy") or ("/usr/bin/scrcpy" if os.path.exists("/usr/bin/scrcpy") else None)
    if not scrcpy_bin:
        console.print("[red]❌ scrcpy is not installed — it is what draws the mirror window.[/red]")
        console.print("[dim]Ubuntu/Debian: sudo apt install scrcpy — on WSL install the "
                      "Linux build here, not the Windows one[/dim]")
        return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id:
        return
    version = scrcpy_version(scrcpy_bin)
    android = _android_release(dev_id)
    try:
        android_major = int(str(android).split(".")[0])
    except ValueError:
        android_major = 0
    if version and version < SCRCPY_MIN_VERSION and android_major >= 14:
        console.print(Panel(
            SCRCPY_TOO_OLD.format(found=".".join(map(str, version)), android=android,
                                  minv=SCRCPY_MIN_VERSION[0], latest="3.3.4"),
            box=box.ROUNDED, border_style="yellow", title_align="left",
            title=Text("MIRROR NEEDS A NEWER SCRCPY", style="yellow"), padding=(0, 1)))
        console.print("[dim]Trying anyway — older scrcpy still mirrors Android up to 13.[/dim]")
    console.print(f"[green]📱 Launching mirror for {dev_key.upper()} ({dev_id})…[/green]")
    ensure_output_dirs()
    log_path = _scrcpy_log_file(dev_id)
    logf = open(log_path, "w", encoding="utf-8")
    env = dict(os.environ, ANDROID_ADB_SERVER_PORT=str(ADB_SERVER_PORT))
    try:
        proc = subprocess.Popen([scrcpy_bin, "-s", dev_id], stdout=logf, stderr=logf,
                                stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True)
    finally:
        logf.close()                     # the child holds its own descriptor
    # A window that is alive a few seconds in has a device to draw. Anything else
    # is a failed launch, which used to be invisible.
    time.sleep(4)
    if proc.poll() is None:
        console.print(f"[green]✅ Mirror window is up.[/green] "
                      f"[dim]Close it on the phone or here; output: {_pretty_path(log_path)}[/dim]")
        return
    tail = ""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-6:])
    except OSError:
        pass
    console.print(f"[red]❌ The mirror window did not come up — it exited "
                  f"{(proc.returncode or '?')} right away.[/red]")
    if tail:
        console.print(f"[dim]Last lines from {_pretty_path(log_path)}:[/dim]")
        for line in tail.strip().splitlines()[-4:]:
            console.print(f"  [dim]·[/dim] {line.strip()[:110]}")
    console.print("[dim]Full output: " + _pretty_path(log_path) + "[/dim]")

# --- Doctor: auto-discover and connect devices ---------------------------------
# Use 'fenox sync' to reconnect known devices, or 'fenox pair' to add new ones.

# --- One-shot connect: plug in (or be on Wi-Fi) and run this — done ---
def _warn_unauthorized_devices():
    """Explain devices that adb sees but can't use (RSA prompt pending / offline)."""
    out = run_cmd("timeout 5 adb devices")
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List"):
            continue
        if line.endswith("unauthorized"):
            console.print(f"[yellow]⏳ {line.split()[0]} is waiting for authorization — accept the 'Allow USB debugging?' prompt on the phone.[/yellow]")
        elif line.endswith("offline"):
            console.print(f"[yellow]⚠️ {line.split()[0]} is offline — unlock the phone screen and replug the cable.[/yellow]")

def action_connect(dev_key="all"):
    """Connect one device or all known devices (no prompts), then bind all ports."""
    console.print(Panel.fit("[bold cyan]⚡ Connecting devices...[/bold cyan]", border_style="cyan"))
    ensure_shared_adb_server()
    targets = list(DEVICES.keys()) if dev_key in (None, "all") else [dev_key]
    ok = []
    for key in targets:
        if key not in DEVICES:
            console.print(f"[red]❌ Unknown device '{key}'. Known: {', '.join(DEVICES.keys())}[/red]")
            continue
        if not is_device_enabled(DEVICES[key]):
            console.print(f"   [yellow]⏭ {key} is disabled (toggle it in the menu).[/yellow]")
            continue
        d_id = check_and_connect(key, interactive=False)
        if d_id:
            ok.append(key)
            kind = "USB" if DEVICES[key].get("type") == "usb" else "wireless"
            console.print(f"   [green]✅ {key} online ({kind})[/green]")
        else:
            console.print(f"   [yellow]⚠️ {key} offline[/yellow]")
    _warn_unauthorized_devices()
    if ok:
        action_bind("all", "all", quiet=False)
        console.print(f"[bold green]✨ {len(ok)} device(s) ready. Launch with e.g. '<app>-{ok[0]}'[/bold green]")
    else:
        console.print("[yellow]No devices connected. Plug in USB (debugging on) or enable Wireless Debugging, then retry.[/yellow]")

def action_sync():
    console.print(Panel.fit("[bold cyan]🔄 Syncing known devices...[/bold cyan]", border_style="cyan"))
    # Silent pass: reconnect with saved ports only — no port prompts yet
    statuses = {}
    for key in DEVICES.keys():
        dev_info = DEVICES[key]
        if not is_device_enabled(dev_info):
            statuses[key] = None
            continue
        console.print(f"-> Checking for {key}...")
        statuses[key] = check_and_connect(key, interactive=False)
        if statuses[key]:
            console.print(f"   [green]✅ Connected to {key}[/green]")
        else:
            console.print(f"   [yellow]⚠️ {key} is offline.[/yellow]")
    # Interactive phase: pick which offline device(s) to fix — ports only for what you pick
    offline = [key for key, d in statuses.items()
               if not d and is_device_enabled(DEVICES.get(key, {})) and DEVICES[key].get("type") not in ("emulator", "usb")]
    if offline:
        for key in _pick_offline_devices(offline):
            console.print(f"-> Retrying {key}...")
            if check_and_connect(key, interactive=True):
                console.print(f"   [green]✅ Connected to {key}[/green]")
            else:
                console.print(f"   [yellow]⚠️ {key} is offline.[/yellow]")
    console.print("\n[bold green]🔄 Sync complete.[/bold green]")




# --- Media Capture (Screenshot/Record) ---
def _open_in_windows(win_filepath):
    try:
        subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", f"Start-Process '{win_filepath}'"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def capture_media(dev_id, label, media_type, open_preview=False):
    ensure_output_dirs()
    wsl_dir, win_dir = OUTPUT_DIRS[media_type]
    dev_sub = os.path.join(wsl_dir, label)
    win_dev_sub = f"{win_dir}\\{label}"
    os.makedirs(dev_sub, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    def _unique_file(base_name):
        wsl_path = os.path.join(dev_sub, base_name)
        n = 1
        while os.path.exists(wsl_path):
            stem, ext = os.path.splitext(base_name)
            wsl_path = os.path.join(dev_sub, f"{stem}_{n}{ext}")
            n += 1
        return os.path.basename(wsl_path)
    if media_type == "screenshot":
        filename = _unique_file(f"screenshot_{label}_{timestamp}.png")
        wsl_filepath = os.path.join(dev_sub, filename)
        win_filepath = f"{win_dev_sub}\\{filename}"
        console.print(f"[yellow]📸 Taking screenshot on {label.upper()}...[/yellow]")
        run_cmd(f"adb -s {dev_id} shell screencap -p /sdcard/fenox_temp.png")
        run_cmd(f"adb -s {dev_id} pull /sdcard/fenox_temp.png \"{wsl_filepath}\"")
        run_cmd(f"adb -s {dev_id} shell rm /sdcard/fenox_temp.png")
        console.print("[yellow]📋 Copying image to Windows clipboard...[/yellow]")
        ps_cmd = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{win_filepath}'))"
        subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-sta", "-Command", ps_cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console.print(f"[green]✅ Saved to {win_filepath} and copied to clipboard![/green]")
        if open_preview:
            _open_in_windows(win_filepath)
    elif media_type == "record":
        filename = _unique_file(f"record_{label}_{timestamp}.mp4")
        wsl_filepath = os.path.join(dev_sub, filename)
        win_filepath = f"{win_dev_sub}\\{filename}"
        console.print(f"[red]🎥 Started recording on {label.upper()}...[/red]")
        subprocess.Popen(["adb", "-s", dev_id, "shell", "screenrecord", "/sdcard/fenox_temp.mp4"])
        Prompt.ask("[cyan]Press Enter to stop recording...[/cyan]")
        run_cmd(f"adb -s {dev_id} shell pkill -INT screenrecord")
        time.sleep(1.5)  # Wait for MP4 to finalize safely
        console.print("[yellow]📥 Pulling video file...[/yellow]")
        run_cmd(f"adb -s {dev_id} pull /sdcard/fenox_temp.mp4 \"{wsl_filepath}\"")
        run_cmd(f"adb -s {dev_id} shell rm /sdcard/fenox_temp.mp4")
        console.print(f"[green]✅ Saved video to {win_filepath}[/green]")
        if open_preview:
            _open_in_windows(win_filepath)

def action_media(dev_key, media_type, open_preview=False):
    if dev_key == "all":
        devs = get_connected_device_ids()
        if not devs:
            console.print("[red]❌ No devices connected.[/red]"); return
        console.print(f"[cyan]📸 Batch {media_type} on {len(devs)} device(s)...[/cyan]")
        for d_id in devs:
            label = run_cmd(f"timeout 4 adb -s {d_id} shell getprop ro.product.model").strip() or d_id
            label = label.replace(" ", "_")
            capture_media(d_id, label, media_type, open_preview=False)
        console.print("[green]✅ Batch capture complete.[/green]")
        return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    capture_media(dev_id, dev_key, media_type, open_preview=open_preview)

# ===================== Power & portability ================================

def _fenox_hook_dir():
    return os.path.expanduser("~/.fenox/hooks")

def _ensure_adb_hook():
    """Install a udev-independent replug watcher: rebinds reverse ports when a USB device reappears."""
    hdir = _fenox_hook_dir()
    hook = os.path.join(hdir, "on_usb.sh")
    want = ("#!/bin/bash\n"
            "# Fenox: rebind reverse ports when a USB device comes back\n"
            "export ANDROID_ADB_SERVER_PORT=5038\n"
            "SER=$(cat \"$1\" 2>/dev/null)\n"
            "[ -z \"$SER\" ] && exit 0\n"
            "sleep 1\n"
            "adb wait-for-device 2>/dev/null\n"
            "CFG=$HOME/.fenox.json\n"
            "[ -f \"$CFG\" ] || exit 0\n"
            "python3 - <<'PYEOF'\n"
            "import json, os, subprocess\n"
            "cfg = json.load(open(os.path.expanduser('~/.fenox.json')))\n"
            "ports = set()\n"
            "for a in cfg.get('apps', {}).values():\n"
            "    ports.add(str(a.get('port', '')))\n"
            "    ports.update(str(p) for p in a.get('additional_ports', []))\n"
            "for p in sorted(ports):\n"
            "    if p and p.isdigit():\n"
            "        subprocess.run(['adb', 'reverse', f'tcp:{p}', f'tcp:{p}'], capture_output=True)\n"
            "PYEOF\n")
    try:
        cur = open(hook).read() if os.path.exists(hook) else ""
        if cur != want:
            os.makedirs(hdir, exist_ok=True)
            with open(hook, "w") as f:
                f.write(want)
            os.chmod(hook, 0o755)
        run_cmd("adb devices >/dev/null 2>&1")  # wake server so hook has a client
    except Exception:
        pass

def _resolve_device_spec(dev_key):
    """Resolve '@group' device-group specs to a comma-joined key set (used by run)."""
    if not dev_key or not str(dev_key).startswith("@"):
        return dev_key
    gname = str(dev_key)[1:]
    members = (config.get("groups", {}) or {}).get(gname, [])
    valid = [m for m in members if m in DEVICES]
    if not valid:
        console.print(f"[red]❌ Group '{gname}' not found or empty. Define it in ~/.fenox.json: \"groups\": {{ \"{gname}\": [\"dev1\", \"dev2\"] }}[/red]")
        return dev_key
    console.print(f"[cyan]👥 Group '{gname}': {', '.join(valid)}[/cyan]")
    return ",".join(valid)

def action_devices(json_out=False):
    """List devices with live status — machine friendly with --json."""
    ensure_shared_adb_server()
    ids = get_connected_device_ids()
    entries = []
    for key, info in DEVICES.items():
        d_id = check_and_connect(key, interactive=False)
        entry = {"alias": key, "type": info.get("type", "wireless"),
                 "model": info.get("model", ""), "id": d_id,
                 "online": bool(d_id), "enabled": is_device_enabled(info)}
        if info.get("ip"): entry["ip"] = info["ip"]
        if info.get("serial"): entry["serial"] = info["serial"]
        entries.append(entry)
    for d_id in ids:  # devices seen by adb but not in config
        if d_id.startswith("emulator-") or ":" in d_id:
            continue
        if not any(e.get("id") == d_id for e in entries):
            entries.append({"alias": None, "type": "usb", "model": "", "id": d_id, "online": True, "enabled": True, "unregistered": True})
    if json_out:
        print(json.dumps({"devices": entries, "adb_server_port": ADB_SERVER_PORT, "wsl": IS_WSL}, indent=2))
        return
    t = Table(title="Connected Devices", box=box.ROUNDED)
    t.add_column("Alias"); t.add_column("Type"); t.add_column("Model"); t.add_column("ID"); t.add_column("Status")
    for e in entries:
        alias = e["alias"] or "[dim](unknown)[/dim]"
        status = "[green]● online[/green]" if e["online"] else "[red]○ offline[/red]"
        if not e["enabled"]: status = "[yellow]⏭ disabled[/yellow]"
        t.add_row(alias, e["type"], e["model"] or "—", e["id"] or "—", status)
    console.print(t)

def action_groups(action=None, name=None, members=None):
    """Manage device groups: fenox groups add testers s21+ s21+usb"""
    groups = config.setdefault("groups", {})
    if action in (None, "list"):
        if not groups:
            console.print("[yellow]No groups yet. Create one:[/yellow] fenox groups add testers s21+ itel")
            return
        t = Table(title="Device Groups", box=box.ROUNDED)
        t.add_column("Group"); t.add_column("Members")
        for g, ms in groups.items():
            t.add_row(f"@{g}", ", ".join(ms))
        console.print(t)
        return
    if action == "add":
        if not name or not members:
            console.print("[red]Usage: fenox groups add <group> <device1> [device2 ...][/red]"); return
        bad = [m for m in members if m not in DEVICES]
        if bad:
            console.print(f"[red]❌ Unknown device(s): {', '.join(bad)}. Known: {', '.join(DEVICES.keys())}[/red]"); return
        groups[name] = sorted(set(groups.get(name, [])) | set(members))
        save_config()
        console.print(f"[green]✅ Group @{name}: {', '.join(groups[name])}[/green]")
        console.print(f"[dim]Run on the whole group: fenox run <app> @{name}[/dim]")
    elif action == "remove":
        if not name or name not in groups:
            console.print(f"[red]❌ Unknown group: {name}. Existing: {', '.join(groups.keys()) or 'none'}[/red]"); return
        del groups[name]
        save_config()
        console.print(f"[green]✅ Group @{name} removed.[/green]")
    else:
        console.print("[red]Usage: fenox groups [list|add|remove] ...[/red]")

def setup_settings(force=False):
    """The one-time questions: where projects live, and the remote API domain.

    Answers are written to ~/.fenox.json, so they are asked once per machine
    (or again with `fenox init --reset-settings`).
    """
    settings = config.setdefault("settings", {})
    changed = False

    unset = (not str(settings.get("projects_dir") or "").strip()
             or not str(settings.get("remote_domain") or "").strip())
    if (force or unset) and not sys.stdin.isatty():
        console.print()
        console.print("[yellow]⚠️  One-time setup needs an interactive terminal.[/yellow]")
        console.print("[dim]Run [cyan]fenox init[/cyan] from a terminal to choose your projects directory "
                      "and remote API domain — until then fenox falls back to "
                      f"[cyan]{get_projects_dir()}[/cyan].[/dim]")
        return False

    if force or not str(settings.get("projects_dir") or "").strip():
        console.print()
        console.print("[bold]1/2 · Where do your Flutter projects live?[/bold]")
        console.print("[dim]Fenox scans this directory to register projects and offers it as the "
                      "default path when adding one.[/dim]")
        answer = _ask("Projects directory", default=settings.get("projects_dir") or get_projects_dir())
        path = os.path.expanduser(str(answer or "").strip())
        while path and not os.path.isdir(path) and _confirm(f"{path} does not exist yet. Create it?", default=True):
            try:
                os.makedirs(path, exist_ok=True)
                console.print(f"[green]✅ Created {path}[/green]")
            except OSError as e:
                console.print(f"[red]❌ Could not create {path}: {e}[/red]")
                break
        if path and os.path.isdir(path):
            settings["projects_dir"] = path
            changed = True
            console.print(f"[green]✅ Projects directory:[/green] {path}")
        else:
            console.print("[yellow]⚠️  Not a directory — keeping the current setting.[/yellow]")

    if force or not str(settings.get("remote_domain") or "").strip():
        console.print()
        console.print("[bold]2/2 · Remote API domain (optional)[/bold]")
        console.print("[dim]Guesses production URLs as https://<app>.<domain>/api. Press Enter to skip.[/dim]")
        answer = str(_ask("Your domain, e.g. example.com", default=settings.get("remote_domain") or "") or "")
        answer = answer.replace("https://", "").replace("http://", "").strip().strip("/")
        if answer:
            settings["remote_domain"] = answer
            changed = True
            console.print(f"[green]✅ Remote domain:[/green] {answer}")
        else:
            console.print("[dim]Skipped — fenox will ask for a URL when a remote launch or "
                          "release build needs one.[/dim]")

    if changed:
        save_config()
    return changed

def action_uninstall(args=None):
    """Remove fenox: shell hooks, config, backups and the installed binary."""
    assume_yes = bool(getattr(args, "yes", False))
    keep_config = bool(getattr(args, "keep_config", False))
    console.print(Panel.fit("[bold red]🗑️  FENOX UNINSTALL[/bold red]", border_style="red"))
    console.print("[dim]This removes fenox from this machine. Nothing is sent anywhere.[/dim]")

    frozen = bool(getattr(sys, "frozen", False))
    self_path = os.path.realpath(sys.executable if frozen else __file__)
    targets = []
    if frozen:
        targets.append(("Binary", self_path))
        link = os.path.join(os.path.dirname(self_path), "fenox")
        if os.path.islink(link) and os.path.realpath(link) == self_path:
            targets.append(("'fenox' symlink", link))
    else:
        # Running from a checkout: never delete the repo we were launched from,
        # only genuine installs in the standard locations.
        console.print(f"[dim]Running from source ({self_path}) — that file is left alone.[/dim]")
        for candidate in (os.path.expanduser("~/.local/bin/fenox"), "/usr/local/bin/fenox"):
            if not os.path.exists(candidate) or os.path.realpath(candidate) == self_path:
                continue
            targets.append(("Installed binary", candidate))
            link = os.path.join(os.path.dirname(candidate), "fenox")
            if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(candidate):
                targets.append(("'fenox' symlink", link))
    if not keep_config:
        targets += [("Config", CONFIG_PATH),
                    ("Run history", HISTORY_PATH),
                    ("Config backups", os.path.expanduser("~/.fenox-backups")),
                    ("Plugins, hooks, profiles", os.path.expanduser("~/.fenox"))]

    if not targets:
        console.print("[dim]Nothing to remove — no install, config or shell hooks found.[/dim]")
        return

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("Remove", style="cyan", no_wrap=True)
    table.add_column("Path")
    for what, path in targets:
        table.add_row(what, path)
    console.print(table)

    hooks = []
    for rc in (os.path.expanduser("~/.bashrc"), os.path.expanduser("~/.zshrc")):
        try:
            if os.path.exists(rc) and "# fenox" in open(rc, encoding="utf-8", errors="ignore").read():
                hooks.append(rc)
        except OSError:
            pass
    if hooks:
        console.print("[cyan]Shell hooks to strip:[/cyan] " + ", ".join(hooks))
    if keep_config:
        console.print("[dim]--keep-config: your ~/.fenox.json is left in place.[/dim]")

    console.print()
    if not assume_yes and not _confirm("Proceed with removal?", default=False):
        console.print("[dim]Cancelled — nothing was removed.[/dim]")
        return

    removed, failed = 0, []
    for _, path in targets:
        if not os.path.exists(path) and not os.path.islink(path):
            continue
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed += 1
            console.print(f"[green]✅ Removed[/green] {path}")
        except OSError as e:
            failed.append(f"{path} ({e})")

    for rc in hooks:
        try:
            lines = open(rc, encoding="utf-8", errors="ignore").read().splitlines(keepends=True)
            kept, skip_next = [], False
            for line in lines:
                if skip_next:
                    skip_next = False
                    # Drop the line under the marker only if it really is ours.
                    if "fenox" in line:
                        continue
                if line.lstrip().startswith("# fenox"):
                    skip_next = True
                    continue
                kept.append(line)
            if len(kept) != len(lines):
                with open(rc, "w", encoding="utf-8") as f:
                    f.writelines(kept)
                console.print(f"[green]✅ Cleaned shell hooks from[/green] {rc}")
        except OSError as e:
            failed.append(f"{rc} ({e})")

    console.print()
    console.print(f"[green]✅ fenox removed ({removed} path(s)).[/green]")
    for f in failed:
        console.print(f"[yellow]⚠️  Could not remove {f}[/yellow]")
    console.print("[dim]Open a new terminal (or run 'hash -r') so the shell hooks take effect.[/dim]")

def action_init(reset=False):
    """One-time setup: environment report, project directory, alias engine, next steps."""
    import platform as _pf
    console.print(Panel.fit("[bold cyan]🚀 FENOX INIT — one-time setup[/bold cyan]", border_style="cyan"))
    plat = "WSL" if IS_WSL else ("macOS" if IS_MACOS else "Linux")
    t = Table(box=box.ROUNDED, show_header=False)
    t.add_column("Key", style="cyan", no_wrap=True)
    t.add_column("Value")
    t.add_row("Version", FENOX_VERSION)
    t.add_row("Platform", f"{plat} ({_pf.machine()})")
    t.add_row("Config", CONFIG_PATH + (" [green]✅[/green]" if os.path.exists(CONFIG_PATH) else " [dim](created on first run)[/dim]"))
    t.add_row("adb server", f"port {ADB_SERVER_PORT}" + (" [dim](shared Windows server)[/dim]" if IS_WSL else ""))
    try:
        t.add_row("Binary", os.path.realpath(__file__))
    except Exception:
        pass
    console.print(t)

    tools = [("adb", "device bridge"), ("scrcpy", "screen mirroring"), ("tmux", "blast deploys"), ("flutter", "Flutter SDK")]
    tt = Table(title="Tool Check", box=box.ROUNDED)
    tt.add_column("Tool"); tt.add_column("Purpose"); tt.add_column("Status"); tt.add_column("Path")
    missing = []
    if IS_MACOS:
        hints = {"adb": "brew install android-platform-tools",
                 "scrcpy": "brew install scrcpy",
                 "tmux": "brew install tmux",
                 "flutter": "see https://docs.flutter.dev/get-started/install/macos"}
        optional = set()
    else:
        hints = {"adb": "sudo apt install adb (or Android platform-tools)",
                 "scrcpy": "sudo apt install scrcpy",
                 "tmux": "sudo apt install tmux",
                 "flutter": "see https://docs.flutter.dev/get-started/install/linux"}
        optional = set()
    for name, what in tools:
        path = shutil.which(name) or shutil.which(name + ".exe")
        if path:
            tt.add_row(name, what, "[green]✅[/green]", path)
        elif name in optional:
            tt.add_row(name, what, "[yellow]optional[/yellow]", "not found")
        else:
            tt.add_row(name, what, "[red]❌[/red]", "not found")
            missing.append(name)
    console.print(tt)
    for m in missing:
        console.print(f"   [yellow]• {m}:[/yellow] {hints.get(m, 'install it and re-run fenox init')}")

    # --- the one-time questions -------------------------------------------------
    setup_settings(force=reset)

    # --- shell integration ------------------------------------------------------
    if sys.stdin.isatty():
        shell = os.path.basename(os.environ.get("SHELL", "bash"))
        rcfile = "~/.zshrc" if "zsh" in shell else "~/.bashrc"
        rc_path = os.path.expanduser(rcfile)
        comp_shell = "zsh" if "zsh" in shell else "bash"
        hooks = (("auto-alias engine", 'eval "$(fenox --generate-aliases)"'),
                 ("shell completions", f'eval "$(fenox --generate-completions {comp_shell})"'))
        for label, line in hooks:
            console.print()
            installed = os.path.exists(rc_path) and line in open(rc_path, encoding="utf-8", errors="ignore").read()
            if installed:
                console.print(f"[green]✅ {label.capitalize()} already installed in {rcfile}[/green]")
                continue
            console.print(f"[cyan]Add the {label} to {rcfile}?[/cyan]")
            if _confirm(f"Append {label} now", default=True):
                with open(rc_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# fenox {label}\n{line}\n")
                console.print(f"[green]✅ Added.[/green] [dim]Run:[/dim] source {rcfile} "
                              "[dim](or open a new terminal)[/dim]")
            else:
                console.print(f"[dim]Skipped — add it anytime: echo '{line}' >> {rcfile}[/dim]")

    # --- offer to find projects straight away -----------------------------------
    projects_dir = get_projects_dir()
    if os.path.isdir(projects_dir):
        console.print()
        if _confirm(f"Scan {projects_dir} for Flutter projects now?", default=True):
            action_scan()

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print("  [cyan]fenox connect[/cyan]        connect every saved device + bind all ports")
    console.print("  [cyan]fenox discover[/cyan]       find wireless-debugging devices on your network")
    console.print("  [cyan]fenox scan[/cyan]           auto-register Flutter projects")
    console.print("  [cyan]fenox doctor[/cyan]         health-check everything")
    console.print("  [cyan]fenox profile import <name>[/cyan]  restore a setup from another machine")
    console.print("  [cyan]fenox uninstall[/cyan]      remove fenox, its config and its shell hooks")

def generate_completions(shell):
    """Print shell completion script (bash or zsh) for fenox commands."""
    cmds = " ".join(sorted(KNOWN_COMMANDS))
    if shell == "zsh":
        zcmds = " ".join(f"'{c}'" for c in sorted(KNOWN_COMMANDS))
        print(f"""#compdef fenox fenox
# fenox zsh completion
_fenox() {{
  local -a cmds
  cmds=({zcmds})
  if (( CURRENT == 2 )); then
    _describe 'command' cmds
  fi
}}
compdef _fenox fenox fenox 2>/dev/null""")
    else:
        print(f"""# fenox bash completion
_fenox_completions() {{
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{cmds}" -- "${{COMP_WORDS[COMP_CWORD]}}") )
    fi
}}
complete -o default -F _fenox_completions fenox 2>/dev/null
complete -o default -F _fenox_completions fenox 2>/dev/null""")

def action_plugin(name, rest):
    """Run a custom plugin from ~/.fenox/plugins/ (foo.py or foo.sh), passing extra args through."""
    pdir = os.path.expanduser("~/.fenox/plugins")
    py_bin = sys.executable if not getattr(sys, "frozen", False) else "python3"
    for ext, how in ((".py", [py_bin]), (".sh", ["bash"])):
        p = os.path.join(pdir, name + ext)
        if os.path.exists(p):
            os.environ.setdefault("ANDROID_ADB_SERVER_PORT", str(ADB_SERVER_PORT))
            rc = subprocess.run(how + [p] + list(rest)).returncode
            sys.exit(rc)
    os.makedirs(pdir, exist_ok=True)
    console.print(f"[red]❌ Plugin '{name}' not found in {pdir}[/red]")
    console.print(f"[dim]Drop a {name}.py or {name}.sh there — it receives ANDROID_ADB_SERVER_PORT and your extra args.[/dim]")

def _ver_key(v):
    """Sortable key for dotted versions, so '1.10.0' outranks '1.9.0' (unlike a plain str compare)."""
    try:
        return tuple(int(p) for p in str(v).strip().lstrip("v").split("."))
    except ValueError:
        return (0,)

def _local_repo_installer():
    """Path to a clone's install.sh on this machine, or None.

    Both the current directory name and the pre-rename one are checked, so an
    existing clone still resolves after the project was renamed.
    """
    for name in ("fenox", "fenox-mobile"):
        candidate = os.path.expanduser(f"~/Projects/{name}/install.sh")
        if os.path.exists(candidate):
            return candidate
    return None

def action_update():
    """Self-update from GitHub releases (or local repo build as fallback)."""
    console.print(Panel.fit("[bold cyan]⬆️ FENOX SELF-UPDATE[/bold cyan]", border_style="cyan"))
    current = FENOX_VERSION
    console.print(f"[cyan]Current version:[/cyan] {current}")

    latest = None
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/repos/{FENOX_REPO}/releases/latest",
            headers={"User-Agent": "fenox-updater", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            latest = json.load(r).get("tag_name", "").lstrip("v")
    except Exception as e:
        console.print(f"[yellow]⚠️ Could not check GitHub ({e}) — trying local build fallback.[/yellow]")
    if latest:
        if latest == current:
            console.print("[green]✅ You are on the latest version.[/green]")
            return
        console.print(f"[cyan]Latest release:[/cyan] {latest}")

    # Path 1: local repo build (developer path, offline-friendly)
    # BUT if the local repo is older than the latest release, prefer downloading.
    repo_install = _local_repo_installer()
    repo_ver = None
    if repo_install:
        try:
            repo_ver = open(os.path.join(os.path.dirname(repo_install), "VERSION")).read().strip()
        except Exception:
            repo_ver = None
    if latest and repo_ver and _ver_key(repo_ver) < _ver_key(latest):
        console.print(f"[yellow]Local repo is v{repo_ver} — older than release v{latest}. Downloading instead.[/yellow]")
    elif repo_install:
        if not Confirm.ask(f"Rebuild+install from the local repo ({os.path.dirname(repo_install)})?", default=True):
            return
        rc = os.system(f"bash '{repo_install}'")
        if rc == 0:
            console.print("[green]✅ Update complete.[/green]")
        else:
            console.print("[red]❌ Installer exited with an error.[/red]")
        return

    # Path 2: download prebuilt binary from GitHub releases
    if not latest:
        console.print("[red]❌ No local repo and no release info — cannot update.[/red]"); return
    import platform as _platform
    arch = "aarch64" if _platform.machine() in ("aarch64", "arm64") else "x86_64"
    asset = f"fenox-linux-{arch}"
    base = f"https://github.com/{FENOX_REPO}/releases/download/v{latest}"
    tmp_bin = f"/tmp/fenox.update.{os.getpid()}"
    tmp_sum = tmp_bin + ".sha256"
    try:
        import urllib.request
        console.print(f"[cyan]Downloading {asset} v{latest}...[/cyan]")
        with urllib.request.urlopen(base + "/" + asset, timeout=60) as resp, open(tmp_bin, "wb") as out:
            out.write(resp.read())
        # Checksum: prefer the aggregate SHA256SUMS, fall back to per-asset .sha256.
        # Match the asset name exactly, so a "<asset>.sha256" entry can't be picked up.
        got_sum = False
        try:
            with urllib.request.urlopen(base + "/SHA256SUMS", timeout=30) as resp:
                for line in resp.read().decode().splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1].lstrip("*") == asset:
                        with open(tmp_sum, "w") as sum_out:
                            sum_out.write(line)
                        got_sum = True
                        break
        except Exception:
            pass
        if not got_sum:
            with urllib.request.urlopen(base + "/" + asset + ".sha256", timeout=30) as resp, open(tmp_sum, "w") as out:
                out.write(resp.read().decode())
    except Exception as e:
        console.print(f"[red]❌ Download failed: {e}[/red]"); return
    if not _verify_sha256(tmp_bin, tmp_sum):
        console.print("[red]❌ Checksum mismatch — aborting (binary NOT installed).[/red]")
        _rm_quiet(tmp_bin, tmp_sum)
        return
    try:
        os.chmod(tmp_bin, 0o755)
        os.replace(tmp_bin, os.path.realpath(__file__))
    except PermissionError:
        console.print("[red]❌ Cannot replace the binary (permission denied). Re-run with sudo or reinstall to ~/.local/bin.[/red]")
        _rm_quiet(tmp_bin, tmp_sum)
        return
    _rm_quiet(tmp_sum)
    console.print(f"[green]✅ Updated to v{latest}. Run 'fenox --version' to confirm.[/green]")

def _rm_quiet(*paths):
    """Best-effort cleanup of updater temp files."""
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass

def _verify_sha256(path, sumfile):
    """Check path's sha256 against the digest written in sumfile."""
    import hashlib
    try:
        expected = open(sumfile).read().split()[0].strip().lower()
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest() == expected and len(expected) == 64
    except Exception:
        return False

def action_profile(action, profile_name=None, *, quiet=False):
    """Snapshot or restore your entire fenox setup (devices, apps, groups) to a JSON file."""
    if action not in ("export", "import", "list"):
        console.print("[red]Usage: fenox profile export|import|list [name][/red]"); return
    prof_dir = os.path.expanduser("~/.fenox/profiles")
    os.makedirs(prof_dir, exist_ok=True)
    if action == "list":
        profiles = sorted(os.listdir(prof_dir))
        if not profiles:
            console.print("[yellow]No profiles yet. Create one:[/yellow] fenox profile export mysetup")
            return
        t = Table(title="Fenox Profiles", box=box.ROUNDED)
        t.add_column("Profile"); t.add_column("Created")
        for p in profiles:
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(prof_dir, p)))
            t.add_row(p.replace(".json", ""), mt.strftime("%Y-%m-%d %H:%M"))
        console.print(t)
        return
    if not profile_name:
        console.print("[red]Profile name required: fenox profile export|import <name>[/red]"); return
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile_name):
        console.print("[red]❌ Profile name may only contain letters, numbers, '-' and '_'.[/red]"); return
    prof_path = os.path.join(prof_dir, f"{profile_name}.json")
    if action == "export":
        if not quiet:
            console.print(Panel.fit("[bold cyan]📦 FENOX PROFILE EXPORT[/bold cyan]", border_style="cyan"))
        snapshot = {
            "version": 2,
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "devices": config.get("devices", {}),
            "apps": config.get("apps", {}),
            "groups": config.get("groups", {}),
            "adb_server_port": ADB_SERVER_PORT,
        }
        with open(prof_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        if not quiet:
            console.print(f"[green]✅ Saved {prof_path}[/green]")
            console.print("[dim]Copy it to another machine, then: fenox profile import " + profile_name + "[/dim]")
    else:  # import
        if not os.path.exists(prof_path):
            console.print(f"[red]❌ Profile not found: {prof_path}[/red]"); return
        try:
            with open(prof_path) as f:
                snap = json.load(f)
        except Exception as e:
            console.print(f"[red]❌ Corrupt profile: {e}[/red]"); return
        console.print(Panel.fit("[bold cyan]📥 FENOX PROFILE IMPORT[/bold cyan]", border_style="cyan"))
        console.print(f"[cyan]Devices:[/cyan] {len(snap.get('devices', {}))}  [cyan]Apps:[/cyan] {len(snap.get('apps', {}))}  [cyan]Groups:[/cyan] {len(snap.get('groups', {}))}")
        console.print("[yellow]This merges into (and overwrites matching keys in) your current config.[/yellow]")
        if not Confirm.ask("Proceed?", default=False):
            return
        if "devices" in snap: config["devices"] = snap["devices"]
        if "apps" in snap: config["apps"] = snap["apps"]
        if "groups" in snap: config["groups"] = snap["groups"]
        save_config()
        global DEVICES
        DEVICES = config.get("devices", {})
        console.print("[green]✅ Profile imported. Run 'fenox doctor' to verify.[/green]")

def action_watch(interval=3):
    """Live device watcher: rebinds reverse ports automatically when a device (re)connects."""
    console.print(Panel.fit("[bold cyan]👀 FENOX WATCH — auto-rebind on device (re)plug[/bold cyan]", border_style="cyan"))
    console.print("[dim]Ctrl+C to stop.[/dim]\n")
    try:
        while True:
            _ensure_adb_hook()
            connected = set(get_connected_device_ids())
            rebound = []
            for key, info in DEVICES.items():
                if not is_device_enabled(info):
                    continue
                if info.get("type") == "emulator":
                    continue
                d_id = check_and_connect(key, interactive=False)
                if d_id:
                    connected.add(d_id)
            ports = set()
            for a in (config.get("apps", {}) or {}).values():
                p = str(a.get("port", ""))
                if p.isdigit(): ports.add(p)
                for pp in a.get("additional_ports", []) or []:
                    ps = str(pp)
                    if ps.isdigit(): ports.add(ps)
            for d_id in sorted(connected):
                out = run_cmd(f"adb -s {d_id} reverse --list")
                missing = [p for p in sorted(ports) if f"tcp:{p}" not in (out or "")]
                if missing:
                    for p in missing:
                        run_cmd(f"adb -s {d_id} reverse tcp:{p} tcp:{p}")
                    rebound.append(f"{d_id}: {', '.join('tcp:' + p for p in missing)}")
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            if rebound:
                console.print(f"[green][{ts}] 🔗 Rebound:[/green] {'; '.join(rebound)}")
            else:
                console.print(f"[dim][{ts}] {len(connected)} device(s) online — all ports bound[/dim]")
            time.sleep(max(2, int(interval)))
    except KeyboardInterrupt:
        console.print("\n[cyan]👋 Watch stopped.[/cyan]")

# --- Nuke Protocol (Deep Clean) ---
def action_nuke(app_key, dev_key):
    if app_key not in APPS or dev_key not in DEVICES: return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    _ensure_adb_hook()
    
    app_data = APPS[app_key]
    package = resolve_package(app_key)
    if not package:
        package = Prompt.ask(f"[cyan]Enter Android Package Name for {app_key.upper()}[/cyan] (e.g. com.company.app)")
        app_data["package"] = package
        save_config()

    console.print(Panel.fit(f"[bold red]☢️  INITIATING NUKE PROTOCOL FOR {app_key.upper()} ON {dev_key.upper()}[/bold red]", border_style="red"))
    os.chdir(os.path.expanduser(app_data['path']))
    
    console.print("[yellow]1. Wiping Flutter Build Cache (flutter clean)...[/yellow]")
    os.system("flutter clean")
    
    console.print("\n[yellow]2. Fetching fresh dependencies (flutter pub get)...[/yellow]")
    os.system("flutter pub get")
    
    console.print(f"\n[yellow]3. Uninstalling {package} from device to clear all cache/storage...[/yellow]")
    run_cmd(f"adb -s {dev_id} uninstall {package}")
    
    console.print("\n[green]✅ Nuke complete. Commencing fresh launch...[/green]")
    action_run(app_key, dev_key, is_remote=False)

# --- Smart Log Streaming ---
def action_logs(app_key, dev_key):
    if app_key not in APPS or dev_key not in DEVICES: return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    _ensure_adb_hook()
    
    app_data = APPS[app_key]
    package = resolve_package(app_key)
    if not package:
        package = Prompt.ask(f"[cyan]Enter Android Package Name for {app_key.upper()}[/cyan] (e.g. com.company.app)")
        app_data["package"] = package
        save_config()
    
    console.print(f"🔍 Searching for running process of [bold]{package}[/bold] on {dev_key.upper()}...")
    pid = run_cmd(f"adb -s {dev_id} shell pidof -s {package}")
    
    if not pid:
        console.print(f"[red]❌ App '{package}' is not currently running. Launch it first![/red]")
        return
    
    ensure_output_dirs()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"{app_key}_{dev_key}_{timestamp}.log"
    wsl_log = os.path.join(LOGS_DIR, log_name)
    win_log = f"{WIN_LOGS_DIR}\\{log_name}"
    console.print(f"[green]✅ Found PID: {pid}. Streaming logs... (Ctrl+C to stop)[/green]")
    console.print(f"[dim]💾 Auto-saving to {win_log}[/dim]")
    os.system(f"adb -s {dev_id} logcat --pid={pid} -v color 2>&1 | tee '{wsl_log}'")
    crashes = [l for l in open(wsl_log, encoding="utf-8", errors="ignore") if "FATAL" in l or "AndroidRuntime" in l]
    if crashes:
        console.print(f"[red]⚠️ {len(crashes)} crash/fatal line(s) detected:[/red]")
        console.print("")
        console.print("[bold red]🔥 QUICK CRASH TRIAGE — fenox logs " + app_key + " " + dev_key + " --last-crash[/bold red]")
        seen = set()
        for c in crashes[-3:]:
            if c not in seen:
                seen.add(c)
                console.print(f"  [dim]•[/dim] {c.strip()[:160]}")
        for l in crashes[-5:]:
            console.print(f"[red]  {l.strip()[:220]}[/red]")
    else:
        console.print("[green]✅ No crashes detected in this session.[/green]")
    console.print(f"[green]✅ Logs saved to {win_log}[/green]")

# --- Core Actions ---
def _pick_offline_devices(offline):
    """Ask which offline device(s) to try. Returns the keys to attempt ([] = 'skip')."""
    if not offline:
        return []
    console.print(f"\n[yellow]⚠️ Offline devices: {', '.join(offline)}[/yellow]")
    choice = Prompt.ask(
        f"Which device to connect? ({', '.join(offline)} / all / skip)",
        choices=offline + ["all", "skip"],
        default="all",
    )
    if choice == "skip":
        return []
    return offline if choice == "all" else [choice]

def _render_device_health(statuses, title="Device Health"):
    table = Table(title=title, show_header=True)
    table.add_column("Device Alias"); table.add_column("Address"); table.add_column("Type"); table.add_column("Status")
    for key, info in DEVICES.items():
        addr = info.get("ip") or info.get("serial") or info.get("port") or "N/A"
        if info.get("type") == "emulator": dev_type = "🖥️ Emulator"
        elif info.get("type") == "usb": dev_type = "🔌 USB"
        else: dev_type = "📱 Phone"
        if not is_device_enabled(info):
            table.add_row(key, addr, dev_type, "[yellow]⏭ Disabled[/yellow]")
        elif statuses.get(key): table.add_row(key, addr, dev_type, "[green]✅ Connected[/green]")
        else: table.add_row(key, addr, dev_type, "[red]❌ Offline[/red]")
    console.print(table)

def action_doctor():
    console.print(Panel.fit("[bold cyan]🩺 FENOX DOCTOR - System Health Check[/bold cyan]", border_style="cyan"))
    # NEVER kill/restart the adb server: the shared Windows server on port 5038
    # hosts USB devices, and a Linux adb server would immediately squat the same
    # port under mirrored networking (Linux clients reach it fine — see
    # ANDROID_ADB_SERVER_PORT). Just probe + heal if needed.
    # Probe + explain devices stuck on the RSA prompt before the silent pass
    ensure_shared_adb_server()
    run_cmd("timeout 8 adb devices")
    _warn_unauthorized_devices()
    
    # Auto-detect running emulators and add them to config
    emulator_found = False
    for d_id in get_connected_device_ids():
        if d_id.startswith("emulator-"):
            emulator_found = True
            already_known = False
            for key, info in DEVICES.items():
                if info.get("type") == "emulator":
                    already_known = True
                    break
            if not already_known:
                DEVICES["emulator"] = {"type": "emulator", "model": "Android Emulator", "port": d_id.split("-")[1]}
                save_config()
                console.print(f"[green]✅ Auto-detected Android Emulator: {d_id}[/green]")
    if emulator_found:
        console.print("[green]✅ Android Emulator detected![/green]")
    
    # Auto-add USB devices (visible only to the shared Windows adb server)
    for d_id in get_connected_device_ids():
        if d_id.startswith("emulator-") or ":" in d_id:
            continue  # skip emulators and wireless ip:port ids
        already_known = any(info.get("type") == "usb" and str(info.get("serial", "")) == d_id for info in DEVICES.values())
        if already_known:
            continue
        usb_model = run_cmd(f"timeout 4 adb -s {d_id} shell getprop ro.product.model").strip()
        default_name = (usb_model or "usbphone").replace(" ", "").lower() or "usbphone"
        name, n = default_name, 2
        while name in DEVICES:
            name = f"{default_name}{n}"
            n += 1
        DEVICES[name] = {"type": "usb", "serial": d_id, "model": usb_model or "USB device"}
        save_config()
        console.print(f"[green]✅ Auto-added USB device '{name}' ({usb_model or d_id})[/green]")
    
    # Auto-discover devices via mDNS (adb-mdns)
    mdns_devices = run_cmd("adb mdns services 2>/dev/null")
    if mdns_devices and "discovered" in mdns_devices.lower() or "adb-" in mdns_devices:
        for line in mdns_devices.splitlines():
            parts = line.split()
            if len(parts) >= 3 and '_adb-tls-connect' in line:
                svc_name = parts[0]
                svc_addr = parts[2]
                console.print(f"[dim]📡 mDNS: {svc_name} at {svc_addr}[/dim]")
                # Check if we know this IP
                known = False
                for key, info in DEVICES.items():
                    if info.get("type") != "emulator" and info.get("ip", "") in svc_addr:
                        known = True
                        break
                if not known:
                    dev_ip = svc_addr.split(":")[0]
                    console.print(f"[yellow]📡 New device discovered via mDNS: {dev_ip}[/yellow]")
    
    # Silent pass: reconnect with saved ports only — no port prompts yet
    console.print("\n[yellow]Checking wireless devices (saved ports only)...[/yellow]")
    statuses = {}
    for key in DEVICES.keys():
        dev_info = DEVICES[key]
        if not is_device_enabled(dev_info):
            statuses[key] = None
        elif dev_info.get("type") == "emulator":
            statuses[key] = check_and_connect(key, interactive=False)
        else:
            statuses[key] = check_and_connect(key, interactive=False)
            if statuses[key]:
                if dev_info.get("type") == "usb":
                    console.print(f"   [green]✅ {key} connected over USB.[/green]")
                else:
                    console.print(f"   [green]✅ {key} reconnected on saved port.[/green]")
    _render_device_health(statuses)

    # Interactive phase: let the user pick which offline device(s) to try.
    # Ports are only asked for the devices they actually pick — no more grinding through dead phones.
    offline = [key for key, d in statuses.items()
               if not d and is_device_enabled(DEVICES.get(key, {})) and DEVICES[key].get("type") not in ("emulator", "usb")]
    if offline:
        for key in _pick_offline_devices(offline):
            console.print(f"   [yellow]Trying {key}...[/yellow]")
            statuses[key] = check_and_connect(key, interactive=True)
        _render_device_health(statuses, title="Device Health (final)")
    else:
        console.print("\n[green]✅ All wireless devices are connected.[/green]")
    
    # Also list any connected devices not in config
    # Build a set of known identifiers (IPs and model names)
    configured_ids = set()
    for key, info in DEVICES.items():
        if info.get("type") == "emulator":
            continue
        if info.get("ip"):
            configured_ids.add(info["ip"].lower())
        if info.get("serial"):
            configured_ids.add(info["serial"].lower())
        model_key = info.get("model", "").lower().replace(" ", "").replace("_", "")
        if model_key:
            configured_ids.add(model_key)
    for d_id in get_connected_device_ids():
        if not d_id.startswith("emulator-"):
            d_id_lower = d_id.lower()
            # Check if this device's model matches a known config
            connected_model = run_cmd(f"timeout 3 adb -s {d_id} shell getprop ro.product.model 2>/dev/null").lower().replace(" ", "").replace("_", "")
            is_known = any(cid in d_id_lower for cid in configured_ids)
            if not is_known and connected_model:
                is_known = any(cid in connected_model for cid in configured_ids)
            if not is_known:
                console.print(f"[dim]ℹ️  Unknown device connected: {d_id} (use 'fenox pair' to add it)[/dim]")
    
    action_bind("all", "all", quiet=False)
    console.print("\n[green bold]✨ System optimized and ready.[/green bold]")

def action_bind(app_key, dev_key, quiet=False):
    apps_to_bind = list(APPS.keys()) if app_key == "all" else [app_key]
    active_ids = get_connected_device_ids()
    if not active_ids:
        if not quiet: console.print("[red]❌ No devices online to bind ports to.[/red]")
        return
    for a_key in apps_to_bind:
        if a_key not in APPS: continue
        port = APPS[a_key]["port"]
        additional_ports = APPS[a_key].get("additional_ports", [])
        for d_id in active_ids:
            run_cmd(f"adb -s {d_id} reverse tcp:{port} tcp:{port}")
            for add_port in additional_ports:
                run_cmd(f"adb -s {d_id} reverse tcp:{add_port} tcp:{add_port}")
            if not quiet:
                console.print(f"[green]🔗 Bound {a_key.upper()} (Port {port}) on device {d_id}[/green]")
                if additional_ports:
                    extras = ", ".join(str(p) for p in additional_ports)
                    console.print(f"[green]   ↳ Additional reverses: {extras}[/green]")

def action_run(app_key, dev_key, is_remote):
    if app_key not in APPS:
        console.print("[red]❌ Invalid App alias.[/red]"); return
    dev_key = _resolve_device_spec(dev_key)
        
    # --- TMUX BLAST DEPLOYMENT ---
    if dev_key == "all" or "," in dev_key:
        if not shutil.which("tmux"):
            console.print("[red]❌ 'tmux' is not installed. Required for multi-device deployment.[/red]"); return
        # Silent pass with saved ports — no port prompts yet
        online, offline = [], []
        for k in DEVICES.keys():
            dev_info = DEVICES[k]
            if not is_device_enabled(dev_info):
                continue
            if check_and_connect(k, interactive=False):
                online.append(k)
            elif dev_info.get("type") not in ("emulator", "usb"):
                offline.append(k)
        # Let the user pick which offline device(s) to try before launching
        if offline:
            for k in _pick_offline_devices(offline):
                console.print(f"-> Retrying {k}...")
                if check_and_connect(k, interactive=True):
                    online.append(k)
        if not online:
            console.print("[red]❌ No devices online.[/red]"); return
        skipped = [k for k in offline if k not in online]
        if skipped:
            console.print(f"[yellow]⚠️ Still offline (skipped): {', '.join(skipped)}[/yellow]")
            
        session = f"fenox_{app_key}"
        run_cmd(f"tmux kill-session -t {session} 2>/dev/null")
        remote_flag = "--remote" if is_remote else ""
        
        os.system(f"tmux new-session -d -s {session} 'fenox run {app_key} {online[0]} {remote_flag}'")
        os.system(f"tmux set-option -g mouse on")
        for dev in online[1:]:
            os.system(f"tmux split-window -h -t {session} 'fenox run {app_key} {dev} {remote_flag}'")
            os.system(f"tmux select-layout -t {session} even-horizontal")
            
        console.print(f"[green]🚀 Launching {app_key.upper()} on {len(online)} device(s) via tmux...[/green]")
        os.system(f"tmux attach-session -t {session}")
        return

    dev_key = _resolve_device_spec(dev_key)
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    if not _preflight(app_key, dev_key, is_remote):
        return
    action_bind(app_key, dev_key, quiet=True)
    app_data = APPS[app_key]
    args = []
    if not is_remote:
        args.append(f"--dart-define=API_BASE_URL={app_data['api_local']}")
        if "socket_local" in app_data: args.append(f"--dart-define=SOCKET_BASE_URL={app_data['socket_local']}")
    else:
        args.append(f"--dart-define=API_BASE_URL={_remote_api(app_data)}")
        if "socket_remote" in app_data: args.append(f"--dart-define=SOCKET_BASE_URL={app_data['socket_remote']}")
        
    cmd = ["flutter", "run", "-d", dev_id] + args
    console.print(f"\n[green bold]🚀 Launching {app_key.upper()} on {dev_key.upper()}...[/green bold]")
    os.chdir(os.path.expanduser(app_data['path']))
    rc = subprocess.call(cmd)
    log_history(app_key, dev_key, "remote" if is_remote else "local", ok=(rc == 0))

def action_build(app_key):
    if app_key not in APPS: return
    app_data = APPS[app_key]
    remote_api = str(app_data.get("api_remote") or "").strip()
    if not remote_api:
        console.print(f"[red]❌ No remote API URL configured for '{app_key}' — refusing to build a "
                      "release APK that points at nothing.[/red]")
        console.print(f"[dim]Set settings.remote_domain with [cyan]fenox init[/cyan], or re-register: "
                      f"[cyan]fenox add-app --name {app_key} --api-remote https://api.example.com "
                      "--update --yes[/cyan][/dim]")
        return
    args = [f"--dart-define=API_BASE_URL={remote_api}"]
    if "socket_remote" in app_data: args.append(f"--dart-define=SOCKET_BASE_URL={app_data['socket_remote']}")
    cmd = ["flutter", "build", "apk", "--release"] + args
    console.print(f"\n[green bold]📦 Building Release APK for {app_key.upper()}...[/green bold]")
    os.chdir(os.path.expanduser(app_data['path']))
    rc = subprocess.call(cmd)
    log_history(app_key, None, "build", ok=(rc == 0))
    if rc == 0:
        apk = os.path.join(os.path.expanduser(app_data['path']), "build", "app", "outputs", "flutter-apk", "app-release.apk")
        if os.path.exists(apk):
            ensure_output_dirs()
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_name = f"{app_key}_release_{ts}.apk"
            shutil.copy(apk, os.path.join(APKS_DIR, dest_name))
            console.print(f"[green]✅ APK copied to {WIN_APKS_DIR}\\{dest_name}[/green]")
        else:
            console.print("[yellow]⚠️ Build finished but APK not found at the expected path.[/yellow]")
    else:
        console.print("[red]❌ Build failed.[/red]")

# --- Auto Alias Generator ---
def generate_aliases():
    for app in APPS:
        print(f'alias {app}-release="fenox build {app}"')
        print(f'alias {app}-all="fenox run {app} all"')
        print(f'alias {app}-all-remote="fenox run {app} all --remote"')
        for dev in DEVICES:
            print(f'alias {app}-{dev}="fenox run {app} {dev}"')
            print(f'alias {app}-{dev}-remote="fenox run {app} {dev} --remote"')
            print(f'alias {app}-{dev}-bind="fenox bind {app} {dev}"')
            print(f'alias {app}-{dev}-logs="fenox logs {app} {dev}"')
            print(f'alias {app}-{dev}-nuke="fenox nuke {app} {dev}"')
            
    for app in APPS:
        print(f'alias {app}-backend="fenox backend {app}"')
        print(f'alias {app}-hot="fenox hot {app}"')
        print(f'alias {app}-install="fenox install {app}"')
    for dev in DEVICES:
        print(f'alias {dev}-mirror="fenox mirror {dev}"')
        print(f'alias {dev}-screenshot="fenox screenshot {dev}"')
        print(f'alias {dev}-record="fenox record {dev}"')
    
    print('alias fenox-add-app="fenox add-app"')
    print('alias fenox-scan="fenox scan"')
    print('alias fenox-bind-all="fenox bind all all"')
    print('alias fenox-connect="fenox connect"')
    print('alias fenox-rename="fenox rename"')
    print('alias fenox-doctor="fenox doctor"')
    print('alias fenox-sync="fenox sync"')
    print('alias fenox-discover="fenox discover"')
    print('alias fenox-pair="fenox pair"')
    print('alias fenox-pair-qr="fenox pair-qr"')
    print('alias fenox-shot-all="fenox screenshot all"')
    print('alias fenox-reload="source ~/.zshrc"')
    # --- Live alias auto-reload: re-eval aliases whenever ~/.fenox.json changes ---
    # Installed once via the same `eval "$(fenox --generate-aliases)"` line.
    # After add-app / scan / config edits, new aliases just work — no `source` needed.
    print('if [[ -n "$ZSH_VERSION" ]]; then')
    print('  _fenox_maybe_reload() {')
    print('    local cfg="$HOME/.fenox.json" mt=""')
    print('    [[ -f "$cfg" ]] || return')
    print('    if command -v stat >/dev/null 2>&1; then')
    print('      mt=$(stat -c %Y "$cfg" 2>/dev/null || stat -f %m "$cfg" 2>/dev/null)')
    print('    fi')
    print('    if [[ -n "$mt" && "$mt" != "${_FENOX_CFG_MTIME:-}" ]]; then')
    print('      _FENOX_CFG_MTIME=$mt')
    print('      eval "$(fenox --generate-aliases 2>/dev/null)"')
    print('    fi')
    print('  }')
    print('  precmd_functions=(${precmd_functions:#_fenox_maybe_reload})')
    print('  precmd_functions+=(_fenox_maybe_reload)')
    print('fi')
    sys.exit(0)

# --- Quick Device Management (global shortcuts) ---
def action_add_device():
    """Quick-add a device to config (no pairing required)."""
    console.print(Panel.fit("[bold green]➕ ADD NEW DEVICE[/bold green]", border_style="green"))
    alias = Prompt.ask("Device alias (short name)", default="newphone")
    if alias in DEVICES:
        console.print(f"[red]❌ Device '{alias}' already exists. Choose a different name.[/red]")
        return
    dev_type = Prompt.ask("Device type", choices=["phone", "usb", "emulator"], default="phone")
    if dev_type == "emulator":
        port = Prompt.ask("Emulator port", default="5554")
        DEVICES[alias] = {"type": "emulator", "model": "Android Emulator", "port": port}
    elif dev_type == "usb":
        serial = Prompt.ask("USB serial (Enter to auto-detect)", default="")
        if not serial.strip():
            usb_ids = [d for d in get_connected_device_ids() if not d.startswith("emulator-") and ":" not in d]
            if not usb_ids:
                console.print("[red]❌ No USB device detected. Plug it in (with debugging on) and try again.[/red]")
                return
            serial = usb_ids[0]
        model = run_cmd(f"timeout 4 adb -s {serial} shell getprop ro.product.model").strip()
        entry = {"type": "usb", "serial": serial}
        if model:
            entry["model"] = model
        DEVICES[alias] = entry
    else:
        ip = Prompt.ask("Device IP address")
        port = Prompt.ask("Wireless debugging port")
        model = Prompt.ask("Device model (optional)", default="")
        entry = {"ip": ip, "port": port}
        if model.strip():
            entry["model"] = model.strip()
        DEVICES[alias] = entry
    save_config()
    console.print(f"[green]✅ Device '{alias}' added to config.[/green]")
    console.print("[dim]Tip: Use 'p' (Pair) first if this is a new wireless device, then 's' (Sync) to connect.[/dim]")

def action_rename_device(old_key, new_key=None):
    """Rename a device alias (config key). Aliases regenerate automatically."""
    if old_key not in DEVICES:
        console.print(f"[red]❌ Device '{old_key}' not found. Known: {', '.join(DEVICES.keys())}[/red]")
        return
    if new_key is None:
        new_key = Prompt.ask(f"New name for '{old_key}'", default=old_key)
    new_key = re.sub(r"[\s\"'\\\\$;&|<>`]", "_", str(new_key).strip())
    if not new_key:
        console.print("[red]❌ Invalid name.[/red]")
        return
    if new_key == old_key:
        console.print("[yellow]Name unchanged.[/yellow]")
        return
    if new_key in DEVICES:
        console.print(f"[red]❌ '{new_key}' already exists — pick another name.[/red]")
        return
    DEVICES[new_key] = DEVICES.pop(old_key)
    save_config()
    console.print(f"[green]✅ Device '{old_key}' renamed to '{new_key}'.[/green]")
    console.print(f"[dim]Aliases updated instantly: <app>-{new_key}, {new_key}-mirror, {new_key}-screenshot, ...[/dim]")

def action_edit_device():
    """Pick a device and quickly edit its IP/port/model."""
    if not DEVICES:
        console.print("[yellow]No devices configured.[/yellow]")
        return
    console.print(Panel.fit("[bold bright_yellow]✏️  EDIT DEVICE[/bold bright_yellow]", border_style="yellow"))
    keys = list(DEVICES.keys())
    for i, key in enumerate(keys, 1):
        info = DEVICES[key]
        if info.get("type") == "emulator":
            addr = f"emulator:{info.get('port', '')}"
        elif info.get("type") == "usb":
            addr = f"usb:{info.get('serial', '')}"
        else:
            addr = f"{info.get('ip', '')}:{info.get('port', '')}"
        console.print(f"  [bold bright_white]{i}.[/bold bright_white] {key}  [dim]({info.get('model', '?')} — {addr})[/dim]")
    choice = Prompt.ask("Pick device # (or 'cancel')", choices=[str(i) for i in range(1, len(keys)+1)] + ["cancel"], default="cancel")
    if choice == "cancel":
        console.print("[dim]Cancelled.[/dim]")
        return
    key = keys[int(choice) - 1]
    info = DEVICES[key]
    console.print(f"\n[dim]Editing '{key}' — press Enter to keep current value.[/dim]\n")
    if info.get("type") == "emulator":
        new_port = Prompt.ask("  Port", default=str(info.get("port", "5554")))
        new_model = Prompt.ask("  Model", default=info.get("model", "Android Emulator"))
        info["port"] = new_port
        info["model"] = new_model
    elif info.get("type") == "usb":
        new_serial = Prompt.ask("  Serial", default=str(info.get("serial", "")))
        new_model = Prompt.ask("  Model", default=info.get("model", ""))
        info["serial"] = new_serial
        if new_model.strip():
            info["model"] = new_model.strip()
    else:
        new_ip = Prompt.ask("  IP address", default=info.get("ip", ""))
        new_port = Prompt.ask("  Wireless debugging port", default=str(info.get("port", "")))
        new_model = Prompt.ask("  Model", default=info.get("model", ""))
        info["ip"] = new_ip
        info["port"] = new_port
        if new_model.strip():
            info["model"] = new_model.strip()
    DEVICES[key] = info
    save_config()
    console.print(f"\n[green]✅ Device '{key}' updated.[/green]")

def action_toggle_device():
    """Pick a device and toggle its enabled/disabled state."""
    if not DEVICES:
        console.print("[yellow]No devices configured.[/yellow]")
        return
    console.print(Panel.fit("[bold bright_yellow]⏯  TOGGLE DEVICE[/bold bright_yellow]", border_style="yellow"))
    keys = list(DEVICES.keys())
    for i, key in enumerate(keys, 1):
        info = DEVICES[key]
        disabled = info.get("disabled", False)
        status = "[yellow]⏭ OFF[/yellow]" if disabled else "[green]● ON[/green]"
        if info.get("type") == "emulator":
            addr = f"emulator:{info.get('port', '')}"
        elif info.get("type") == "usb":
            addr = f"usb:{info.get('serial', '')}"
        else:
            addr = f"{info.get('ip', '')}:{info.get('port', '')}"
        console.print(f"  [bold bright_white]{i}.[/bold bright_white] {key}  [dim]({info.get('model', '?')})[/dim]  {status}")
    choice = Prompt.ask("Pick device # (or 'cancel')", choices=[str(i) for i in range(1, len(keys)+1)] + ["cancel"], default="cancel")
    if choice == "cancel":
        console.print("[dim]Cancelled.[/dim]")
        return
    key = keys[int(choice) - 1]
    DEVICES[key]["disabled"] = not DEVICES[key].get("disabled", False)
    save_config()
    state = "disabled" if DEVICES[key]["disabled"] else "enabled"
    console.print(f"[green]✅ Device '{key}' {state}.[/green]")

def action_delete_device():
    """Pick a device from the list and remove it."""
    if not DEVICES:
        console.print("[yellow]No devices configured.[/yellow]")
        return
    console.print(Panel.fit("[bold red]🗑  DELETE DEVICE[/bold red]", border_style="red"))
    keys = list(DEVICES.keys())
    for i, key in enumerate(keys, 1):
        info = DEVICES[key]
        addr = info.get("ip", info.get("port", "N/A"))
        console.print(f"  {i}. {key} ({info.get('model', '?')} — {addr})")
    choice = Prompt.ask("Enter # to delete (or 'cancel')", choices=[str(i) for i in range(1, len(keys)+1)] + ["cancel"], default="cancel")
    if choice == "cancel":
        console.print("[dim]Cancelled.[/dim]")
        return
    idx = int(choice) - 1
    key = keys[idx]
    if Confirm.ask(f"[red]Remove device '{key}' ({DEVICES[key].get('model', '?')}) from config?[/red]", default=False):
        del DEVICES[key]
        save_config()
        console.print(f"[green]✅ Device '{key}' removed.[/green]")
    else:
        console.print("[dim]Cancelled.[/dim]")

# --- Interactive Dashboard ---
def _human_ago(ts_iso):
    try:
        t = datetime.datetime.fromisoformat(ts_iso)
        delta = datetime.datetime.now() - t
        secs = delta.total_seconds()
        if secs < 90: return "just now"
        if secs < 3600: return f"{int(secs//60)}m ago"
        if secs < 86400: return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except Exception:
        return ts_iso or "?"

def _git_status(path):
    if not os.path.isdir(os.path.join(path, ".git")):
        return "—"
    branch = run_cmd(f"git -C '{path}' rev-parse --abbrev-ref HEAD 2>/dev/null").strip()
    dirty = run_cmd(f"git -C '{path}' status --porcelain 2>/dev/null").strip()
    if not branch: return "—"
    return f"[green]{branch}[/green]" + (" [yellow]✗ dirty[/yellow]" if dirty else " [green]✓ clean[/green]")

# --- Interactive input ---------------------------------------------------------
# Menus read keys as they are pressed (raw mode) so navigation feels immediate,
# but every screen also accepts a typed line and Enter. Everything degrades to
# line input when stdin is not a TTY, so piped input, CI and dumb terminals work.
try:
    import termios as _termios
    import tty as _tty
except ImportError:
    _termios = _tty = None

# Names are lowercase so they can be compared against option and back keys directly.
_ESCAPE_KEYS = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left"}

def _read_key(timeout=None):
    """Read one key as it is pressed.

    Returns a single lowercased character, or one of up/down/left/right/esc/
    enter/backspace. Returns None on timeout, or immediately when stdin is not an
    interactive terminal.
    """
    if not sys.stdin.isatty():
        return None

    if _termios is None:
        return None

    # Read the raw fd, never sys.stdin's buffer: a buffered read can pull in the
    # rest of an escape sequence, which then looks like nothing arrived and an
    # arrow key gets mistaken for Escape (i.e. "quit").
    import select
    fd = sys.stdin.fileno()
    old = _termios.tcgetattr(fd)
    try:
        _tty.setcbreak(fd)
        if not select.select([fd], [], [], timeout)[0]:
            return None
        data = os.read(fd, 1)
    finally:
        _termios.tcsetattr(fd, _termios.TCSADRAIN, old)

    if not data:
        return "eof"                           # stdin closed, not a timeout
    ch = data.decode("utf-8", "ignore")
    if ch == "\x1b":                           # Esc, or the start of an arrow key
        if not select.select([fd], [], [], 0.1)[0]:
            return "esc"                       # nothing followed: a real Escape
        seq = ch
        while len(seq) < 6:
            if not select.select([fd], [], [], 0.05)[0]:
                break
            nxt = os.read(fd, 1)
            if not nxt:
                break
            seq += nxt.decode("utf-8", "ignore")
            if seq[-1].isalpha() or seq[-1] == "~":
                break
        # Anything unrecognised reports as empty rather than Escape: a missed
        # arrow key must never be read as "quit".
        return _ESCAPE_KEYS.get(seq, "")
    if ch in ("\r", "\n"): return "enter"
    if ch in ("\x7f", "\x08"): return "backspace"
    if ch == "\x03": raise KeyboardInterrupt
    return ch.lower()

def _wait_any_key(hint="press Enter to continue"):
    """Pause so an action's output can be read, then continue."""
    if not sys.stdin.isatty():
        return
    console.print(f"\n  [dim]{hint}…[/dim]")
    while True:                       # Enter and Esc both move on
        key = _read_key()             # Ctrl+C here means "quit" — never swallowed
        if key in (None, "enter", "esc", "eof"):
            return

# --- Screen chrome -----------------------------------------------------------
# Every interactive screen is assembled from the same three pieces: a header bar
# (where you are, and the state of things), one or more bordered sections of
# choices, and a footer holding the key legend. Screens therefore read as one
# application instead of a series of unrelated prompts.

# Layout switches to side-by-side sections at this width; below it everything
# stacks, so the dashboard still fits an 80-column terminal.
TWO_COLUMN_WIDTH = 100


def _entry_parts(o):
    """Normalise one option entry to (key, label, detail, column).

    A `key` of None marks a section header: it is drawn, but the cursor skips it.
    """
    return (o[0],
            o[1] if len(o) > 1 else "",
            o[2] if len(o) > 2 else "",
            o[3] if len(o) > 3 else 1)

def _plain(text):
    """Visible width in terminal cells of a string that may carry rich markup.

    Cell width, not character count: an emoji or CJK character takes two columns,
    and measuring by characters is what makes a labelled column look truncated.
    """
    return cell_len(Text.from_markup(str(text)).plain)

def _resolve(value):
    """Read a screen field that may be a value or a callable (live screens)."""
    return value() if callable(value) else value

def _header_bar(title, breadcrumb, subtitle, accent):
    """The bar across the top of every screen: identity left, live state right."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right")
    left = "[bold bright_white]⚡ FENOX[/bold bright_white]"
    if title:
        left += f"   [dim]│[/dim]   [bold bright_white]{title}[/bold bright_white]"
    grid.add_row(Text.from_markup(left),
                 Text.from_markup(f"[dim]{breadcrumb}[/dim]") if breadcrumb else Text(""))
    if subtitle:
        grid.add_row(Text.from_markup(f"[dim]{subtitle}[/dim]"), Text(""))
    return Panel(grid, box=box.HEAVY, border_style=accent, padding=(0, 1))

def _section_panel(title, rows, cursor, accent, key_w, label_w, has_detail, max_width):
    """One bordered group of choices, drawn on the screen's shared column grid.

    `rows` are (key, label, detail, ordinal), where ordinal is the row's place in
    the screen's selectable order — that is what the cursor compares against. The
    key and label widths come from the whole screen, so sections line up with each
    other instead of each inventing its own layout.
    """
    lines = []
    for key, label, detail, ordinal in rows:
        selected = ordinal is not None and ordinal == cursor
        line = Text()
        line.append("▸ " if selected else "  ", style=f"bold {accent}" if selected else "")
        line.append(f"{key}".rjust(key_w) + "  ",
                    style=f"bold {accent}" if selected else "dim")
        line.append(str(label), style="bold bright_white" if selected else "dim")
        if has_detail:
            line.append(" " * max(0, label_w - _plain(label) + 2))
            line.append_text(Text.from_markup(str(detail)))
        line.truncate(max_width, overflow="ellipsis")
        lines.append(line)
    return Panel(Group(*lines), box=box.ROUNDED, border_style="grey35",
                 title=Text(title, style=accent) if title else None,
                 title_align="left", padding=(0, 1))

def _footer_bar(status, footer):
    """The line under the sections: at-a-glance status left, key legend right."""
    if not status:
        return Text.from_markup(footer)
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right")
    grid.add_row(Text.from_markup(status), Text.from_markup(footer))
    return grid

def _input_bar(typed, matched, accent):
    """The prompt line: what you have typed, with a caret, and what it will do.

    Numbers longer than a single digit need somewhere to accumulate, so every
    keystroke lands here first and Enter commits it. The line is always visible,
    which is also the affordance that says the screen accepts typing.
    """
    if typed:
        hint = "[dim]Enter open · Backspace delete · Esc clears[/dim]"
    else:
        hint = "[dim]type a number or a key, then Enter[/dim]"
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right")
    line = Text("  ❯ ", style=f"bold {accent}")
    if typed:
        line.append(typed, style="bold bright_white" if matched else "bold red")
    line.append("▌", style=accent if (not typed or matched) else "red")
    grid.add_row(line, Text.from_markup(hint))
    return grid

def _menu_renderable(title, options, body, breadcrumb, subtitle, footer, accent,
                     cursor=0, two_col=False, status=None, typed=None, matched=True):
    """Assemble a whole screen from its header, sections and footer.

    Options are (key, label[, detail[, column]]), with a key of None for a section
    header. Sections holding a `detail` get an aligned status column, so rows read
    like a table instead of loose text.
    """
    entries, ordinal = [], 0
    for raw in options:
        key, label, detail, column = _entry_parts(raw)
        entries.append((key, label, detail, column, None if key is None else ordinal))
        ordinal += 0 if key is None else 1

    parts = [_header_bar(title, _resolve(breadcrumb), _resolve(subtitle), accent)]
    rendered_body = _resolve(body)
    if rendered_body is not None:
        parts.append(rendered_body)

    # Group by column first, then by whichever section header precedes each row.
    buckets = {}
    for key, label, detail, column, ordn in entries:
        section = buckets.setdefault(column, [])
        if key is None:
            section.append((label, []))
            continue
        if not section:
            section.append(("", []))
        section[-1][1].append((key, label, detail, ordn))

    # One column grid for the whole screen, so DEVICES, APPS and ACTIONS share it.
    # Only rows that carry a status widen the label column: those are the ones the
    # status has to line up beside. Sizing it from long action labels instead would
    # push the device details off the edge for no gain.
    selectable = [e for e in entries if e[0] is not None]
    detailed = [e for e in selectable if e[2]]
    key_w = max([_plain(e[0]) for e in selectable] or [1])
    label_w = min(max([_plain(e[1]) for e in detailed] or [6]), 32)
    has_detail = bool(detailed)

    side_by_side = bool(two_col and console.size.width >= TWO_COLUMN_WIDTH
                        and buckets.get(1) and buckets.get(2))
    # Each panel spends 4 cells on its borders and padding. Side by side, the two
    # cells are equal and the gutter between them costs 2, so the pair still ends
    # flush with the right edge instead of leaving a ragged gap.
    width = console.size.width
    cell = (width - 2) // 2 if side_by_side else width
    panels = {column: [_section_panel(name, rows, cursor, accent, key_w, label_w,
                                      has_detail, max(20, cell - 4))
                       for name, rows in grouped if rows]
              for column, grouped in buckets.items()}

    if side_by_side:
        grid = Table.grid(expand=True, padding=(0, 1), pad_edge=False)
        grid.add_column(width=cell)
        grid.add_column(width=cell)
        grid.add_row(Group(*panels[1]), Group(*panels[2]))
        parts.append(grid)
    else:
        for column in sorted(panels):
            parts.extend(panels[column])
    if typed is not None:                      # interactive screens only
        parts.append(_input_bar(typed, matched, accent))
    if footer:
        parts.append(_footer_bar(_resolve(status), footer))
    return Group(*parts)

def _key_hint(back_keys):
    """The one-line key legend shown under every set of choices."""
    names = {"b": "b", "x": "x", "esc": "Esc"}
    back = "/".join(names.get(k, k) for k in back_keys if k)
    return (f"[dim]↑/↓ or a row's key   [bold bright_white]Enter[/bold bright_white] opens   "
            f"[bold bright_white]{back}[/bold bright_white] back[/dim]")

def run_menu(title=None, options=(), *, body=None, breadcrumb="", subtitle=None,
             footer=None, interval=0.0, accent="bright_cyan",
             back_keys=("b", "esc"), state=None, start=0, two_col=False, status=None):
    """Draw a screen, move with ↑/↓, confirm with Enter.

    options    : rows of (key, label[, detail[, column]]) or (None, "SECTION") for a
                 heading; may be a callable, so a live screen can rebuild its rows
    body       : renderable (or callable returning one) drawn above the sections
    breadcrumb : right-hand side of the header bar; may be a callable
    subtitle   : dim second line of the header bar; may be a callable
    status     : left-hand side of the footer bar; may be a callable
    interval   : seconds between automatic refreshes; >0 makes the screen live
    two_col    : allow sections in column 2 to sit beside column 1 on wide screens
    back_keys  : keys meaning "go back"; returns None for those
    state      : caller-owned dict, so the cursor survives re-entering a screen
    start      : row to select first

    Enter confirms the highlighted row, and typing a row's own key confirms that
    row straight away — so `1` opens device 1 without arrowing to it first. Unknown
    keys are ignored, never an error.
    """
    holder = state if state is not None else {}
    holder.setdefault("cursor", start)
    holder.setdefault("typed", "")

    def current_options():
        return list(options() if callable(options) else options)

    def selectable():
        """Keys and labels of the rows the cursor can land on, in screen order."""
        keys, labels = [], []
        for raw in current_options():
            key = raw[0]
            if key is None:                    # section heading
                continue
            keys.append(str(key).lower())
            labels.append(key)
        return keys, labels

    def draw():
        # The body is rendered first: on the dashboard it is what produces the
        # device and app rows that the sections are built from.
        items = current_options()               # one read per redraw, never two
        keys = [str(raw[0]).lower() for raw in items if raw[0] is not None]
        holder["cursor"] = max(0, min(holder["cursor"], len(keys) - 1)) if keys else 0
        typed = holder["typed"]
        return _menu_renderable(title, items, body, breadcrumb, subtitle,
                                footer or _key_hint(back_keys), accent,
                                holder["cursor"], two_col, status,
                                typed, not typed or typed.strip().lower() in keys)

    if not sys.stdin.isatty():                 # scripts, pipes, dumb terminals
        holder["typed"] = ""                    # no prompt line without a terminal
        console.print(draw())
        # Offer whichever back key is not already an option, so piping input can
        # never silently fire a short-cut ("b" means bind, not back, on the main menu).
        keys, _ = selectable()
        back = next((k for k in back_keys if k and k not in keys), "b")
        answer = Prompt.ask("▸", choices=keys + [back], default=back).lower()
        return None if answer in back_keys else answer

    keep = object()                            # sentinel: the menu stays open

    def react(key):
        """Act on one keypress: return the chosen key, or `keep` to wait for more."""
        # None reaches here only on a non-live screen (the live loop redraws on a
        # timeout instead), which means the key reader could not deliver a key at
        # all — leave the screen rather than spinning on it.
        if key is None or key == "eof":
            return None
        if key in back_keys:
            # Esc clears whatever was typed before it leaves, but the others always
            # leave: a single stray keystroke must never make quitting impossible
            # ("x" clearing the input instead of quitting left the screen stuck).
            if holder["typed"] and key == "esc":
                holder["typed"] = ""
                return keep
            return None
        if key == "backspace":
            holder["typed"] = holder["typed"][:-1]
            return keep
        keys, labels = selectable()
        if not labels:
            return keep
        if key in ("up", "down"):
            # Arrows are a different intent from typing: they drop the input.
            step = 1 if key == "down" else -1
            holder["cursor"] = (holder["cursor"] + step) % len(labels)
            holder["typed"] = ""
            return keep
        if key == "enter":
            typed = holder["typed"].strip().lower()
            if not typed:                      # nothing typed: open the highlighted row
                return labels[holder["cursor"]]
            return labels[keys.index(typed)] if typed in keys else keep
        if len(key) == 1 and key.isprintable():
            holder["typed"] += key
            typed = holder["typed"].strip().lower()
            if typed in keys:                  # preview the row the input names
                holder["cursor"] = keys.index(typed)
        return keep                            # unknown keys are simply ignored

    # Ctrl+C is deliberately not caught anywhere in here: it unwinds to _main,
    # which prints the sign-off once and exits 130. Live is used even for static
    # screens so the highlight moves in place instead of reprinting the menu.
    with Live(draw(), console=console, screen=bool(interval),
              refresh_per_second=2, auto_refresh=bool(interval)) as live:
        nxt = time.monotonic() + interval if interval else None
        while True:
            key = _read_key(timeout=0.2 if interval else None)
            if key is None and interval:      # live screen: nothing typed yet, redraw
                if nxt and time.monotonic() >= nxt:
                    live.update(draw())
                    nxt = time.monotonic() + interval
                continue
            result = react(key)
            if result is not keep:
                return result
            live.update(draw(), refresh=True)

def _banner():
    """Header banner: what this is, and how much is set up on this machine."""
    total_devices = len(DEVICES)
    total_apps = len(APPS)
    header = Text.from_markup(
        f"[bold bright_white]⚡ FENOX[/bold bright_white]"
        f"  [dim bright_white]│[/dim bright_white]  "
        f"[bright_cyan]ENVIRONMENT MANAGER[/bright_cyan]"
        f"  [dim bright_white]│[/dim bright_white]  "
        f"[bold]{total_devices}[/bold] [dim]{'device' if total_devices == 1 else 'devices'}[/dim]"
        f"  [dim]•[/dim]  "
        f"[bold]{total_apps}[/bold] [dim]{'app' if total_apps == 1 else 'apps'}[/dim]"
    )
    return Panel(header, box=box.HEAVY, border_style="bright_blue", padding=(0, 1))

def _device_row(key, info, connected_ids):
    """One dashboard row: the device, then the status worth seeing at a glance."""
    if info.get("type") == "emulator":
        dev_id = next((cid for cid in connected_ids if cid.startswith("emulator-")), None)
    elif info.get("type") == "usb":
        dev_id = info.get("serial") if info.get("serial") in connected_ids else None
    else:
        dev_id = next((cid for cid in connected_ids if info.get("ip", "") in cid), None)
    model = info.get("model") or "Android device"
    if not is_device_enabled(info):
        return f"📱 {key}", f"{model} · [yellow]disabled[/yellow]"
    if not dev_id:
        return f"📱 {key}", f"{model} · [red]● offline[/red]"
    tele = get_device_telemetry(dev_id)
    bits = [model, "[bold green]● online[/bold green]"]
    battery = str(tele.get("battery", "?"))
    if battery.isdigit():
        level = int(battery)
        colour = "red" if level <= 15 else ("yellow" if level <= 30 else "green")
        bits.append(f"[{colour}]🔋 {level}%{' ⚡' if tele.get('charging') else ''}[/{colour}]")
    screen = tele.get("screen")
    if screen:
        bits.append(f"[green]☀ {screen}[/green]" if screen == "On" else f"[dim]☾ {screen}[/dim]")
    if tele.get("app"):
        bits.append(f"[dim]{tele['app']}[/dim]")
    return f"📱 {key}", " · ".join(bits)

def _app_row(key, data):
    """One dashboard row: the app, its git state, and when it was last deployed."""
    git = _git_status(os.path.expanduser(data.get("path", "")))
    last = get_last_run(key)
    if last:
        ago = _human_ago(last.get("ts", ""))
        ok = last.get("ok", False)
        detail = (f"{git} · [dim]{last.get('action', 'run')} {ago}[/dim] "
                  f"[{'green' if ok else 'yellow'}]{'✓' if ok else '✗'}[/]")
    else:
        detail = f"{git} · [dim]never deployed[/dim]"
    return f"📦 {key}", detail

def _open_path(path):
    """Open a file with the platform's default handler (WSL → Windows, else xdg-open)."""
    if IS_WSL:
        _open_in_windows(path)
        return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        console.print("[yellow]No opener found — install xdg-open to preview captures.[/yellow]")
        return
    try:
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        console.print(f"[red]❌ Could not open {path}: {e}[/red]")

def _open_last_capture(key):
    """Open the newest screenshot or recording taken for this device."""
    for wsl_dir, win_dir in ((SHOTS_DIR, WIN_SHOTS_DIR), (RECS_DIR, WIN_RECS_DIR)):
        dev_sub = os.path.join(wsl_dir, key)
        if not os.path.isdir(dev_sub):
            continue
        files = sorted(Path(dev_sub).glob("*"), key=os.path.getmtime, reverse=True)
        if not files:
            continue
        newest = files[0]
        console.print(f"[green]🖼 Opening {newest.name}[/green]")
        _open_path(f"{win_dir}\\{key}\\{newest.name}" if IS_WSL else str(newest))
        return
    console.print("[yellow]No captures yet for this device — take a screenshot first.[/yellow]")

# ═══════════════════════════════════════════════════════════════════════════
#  FUTURISTIC DEVICE COMMAND CENTER
# ═══════════════════════════════════════════════════════════════════════════

def _bar(percent, width=20):
    """Render a Unicode progress bar with color coding."""
    try: pct = int(percent)
    except (ValueError, TypeError): pct = 0
    filled = int(width * min(pct, 100) / 100)
    empty = width - filled
    if pct > 70: c = "green"
    elif pct > 30: c = "yellow"
    else: c = "red"
    return f"[{c}]{'█' * filled}[/][dim]{'░' * empty}[/] {pct}%"

def _pick_installed_app(dev_id, label="app"):
    """Show list of installed apps and let user pick one."""
    result = run_cmd(f"adb -s {dev_id} shell pm list packages -3")
    packages = sorted([l.replace("package:", "") for l in result.splitlines() if l.startswith("package:")])
    if not packages:
        result = run_cmd(f"adb -s {dev_id} shell pm list packages")
        packages = sorted([l.replace("package:", "") for l in result.splitlines() if l.startswith("package:")])
    if not packages:
        console.print("[red]❌ No apps found on device[/red]"); return None
    for i, pkg in enumerate(packages[:40], 1):
        console.print(f"  [cyan]{i:>2}[/cyan]. {pkg}")
    if len(packages) > 40:
        console.print(f"  [dim]... and {len(packages) - 40} more[/dim]")
    choice = Prompt.ask(f"Pick {label} # (or enter package name)", default="1")
    if choice.isdigit() and 1 <= int(choice) <= len(packages):
        return packages[int(choice) - 1]
    elif "." in choice: return choice.strip()
    return None

# ── Screen & Input ─────────────────────────────────────────────────────────
def _action_type_text(dev_id):
    text = Prompt.ask("Text to type on device")
    if not text: return
    safe = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
    run_cmd(f'adb -s {dev_id} shell input text "{safe}"')
    console.print("[green]✅ Typed on device[/green]")

def _action_tap_screen(dev_id):
    x = Prompt.ask("X coordinate", default="540")
    y = Prompt.ask("Y coordinate", default="1200")
    run_cmd(f"adb -s {dev_id} shell input tap {x} {y}")
    console.print(f"[green]✅ Tapped at ({x}, {y})[/green]")

def _action_swipe(dev_id):
    x1 = Prompt.ask("Start X", default="540")
    y1 = Prompt.ask("Start Y", default="1800")
    x2 = Prompt.ask("End X", default="540")
    y2 = Prompt.ask("End Y", default="600")
    dur = Prompt.ask("Duration (ms)", default="300")
    run_cmd(f"adb -s {dev_id} shell input swipe {x1} {y1} {x2} {y2} {dur}")
    console.print(f"[green]✅ Swiped ({x1},{y1}) → ({x2},{y2})[/green]")

def _action_key_combo(dev_id):
    keys = [
        ("1", "Back", "KEYCODE_BACK"), ("2", "Home", "KEYCODE_HOME"),
        ("3", "Recent Apps", "KEYCODE_APP_SWITCH"), ("4", "Power", "KEYCODE_POWER"),
        ("5", "Volume Up", "KEYCODE_VOLUME_UP"), ("6", "Volume Down", "KEYCODE_VOLUME_DOWN"),
        ("7", "Mute", "KEYCODE_VOLUME_MUTE"), ("8", "Camera", "KEYCODE_CAMERA"),
        ("9", "Play/Pause", "KEYCODE_MEDIA_PLAY_PAUSE"), ("10", "Next Track", "KEYCODE_MEDIA_NEXT"),
        ("11", "Prev Track", "KEYCODE_MEDIA_PREVIOUS"), ("12", "Notifications", "KEYCODE_NOTIFICATION"),
        ("13", "Search", "KEYCODE_SEARCH"), ("14", "Tab", "KEYCODE_TAB"),
        ("15", "Enter", "KEYCODE_ENTER"), ("16", "Delete", "KEYCODE_DEL"),
        ("17", "Space", "KEYCODE_SPACE"), ("18", "Escape", "KEYCODE_ESCAPE"),
        ("19", "Page Up", "KEYCODE_PAGE_UP"), ("20", "Page Down", "KEYCODE_PAGE_DOWN"),
    ]
    console.print("\n[bold]Key Combos:[/bold]")
    for k, name, _ in keys:
        console.print(f"  [cyan]{k:>2}[/cyan]. {name}")
    choice = Prompt.ask("Pick key", default="1")
    for k, name, keycode in keys:
        if choice == k:
            run_cmd(f"adb -s {dev_id} shell input keyevent {keycode}")
            console.print(f"[green]✅ Sent: {name}[/green]"); return

def _action_clipboard_copy(dev_id):
    text = Prompt.ask("Text to copy to device clipboard")
    if not text: return
    run_cmd(f'adb -s {dev_id} shell am broadcast -a clipper.set -e text "{text}" 2>/dev/null')
    console.print("[green]✅ Copied to device clipboard[/green]")
    console.print("[dim]Tip: Long-press a text field → Paste[/dim]")

def _action_clipboard_read(dev_id):
    result = run_cmd(f"adb -s {dev_id} shell service call clipboard 2 i32 1 2>/dev/null")
    console.print("[cyan]📋 Device clipboard:[/cyan]")
    console.print(f"  {result or '[dim]Could not read (needs Clipper service or root)[/dim]'}")

def _action_open_url(dev_id):
    url = Prompt.ask("URL to open on device")
    if not url: return
    if not url.startswith(("http://", "https://")): url = f"https://{url}"
    run_cmd(f'adb -s {dev_id} shell am start -a android.intent.action.VIEW -d "{url}"')
    console.print(f"[green]✅ Opened: {url}[/green]")

# ── App Management ─────────────────────────────────────────────────────────
def _action_list_apps(dev_id):
    console.print("[cyan]📦 Third-party apps:[/cyan]")
    result = run_cmd(f"adb -s {dev_id} shell pm list packages -3")
    packages = sorted([l.replace("package:", "") for l in result.splitlines() if l.startswith("package:")])
    if not packages:
        result = run_cmd(f"adb -s {dev_id} shell pm list packages")
        packages = sorted([l.replace("package:", "") for l in result.splitlines() if l.startswith("package:")])
    for i, pkg in enumerate(packages, 1):
        console.print(f"  [dim]{i:>3}.[/dim] {pkg}")
    console.print(f"\n[dim]Total: {len(packages)} packages[/dim]")

def _action_uninstall_app(dev_id):
    pkg = _pick_installed_app(dev_id, "app to uninstall")
    if not pkg: return
    if Confirm.ask(f"[red]Uninstall {pkg}?[/red]", default=False):
        result = run_cmd(f"adb -s {dev_id} uninstall {pkg}")
        console.print("[green]✅ Uninstalled[/green]" if "Success" in result else f"[red]❌ {result.strip()[:200]}[/red]")

def _action_clear_app_data(dev_id):
    pkg = _pick_installed_app(dev_id, "app to clear data")
    if not pkg: return
    if Confirm.ask(f"[red]Clear ALL data for {pkg}? Cannot be undone.[/red]", default=False):
        result = run_cmd(f"adb -s {dev_id} shell pm clear {pkg}")
        console.print("[green]✅ Data cleared[/green]" if "Success" in result else f"[red]❌ {result.strip()[:200]}[/red]")

def _action_force_stop(dev_id):
    pkg = _pick_installed_app(dev_id, "app to force stop")
    if not pkg: return
    run_cmd(f"adb -s {dev_id} shell am force-stop {pkg}")
    console.print(f"[green]✅ Force stopped {pkg}[/green]")

def _action_app_info(dev_id):
    pkg = _pick_installed_app(dev_id, "app to inspect")
    if not pkg: return
    console.print(Panel(f"[bold]App Info: {pkg}[/bold]", border_style="cyan"))
    for label, cmd in [
        ("Version", f"dumpsys package {pkg} | grep versionName | head -1"),
        ("Install", f"dumpsys package {pkg} | grep firstInstallTime | head -1"),
        ("Data dir", f"dumpsys package {pkg} | grep dataDir | head -1"),
        ("APK", f"pm path {pkg} | head -1"),
        ("Permissions", f"dumpsys package {pkg} | grep 'permission' | wc -l"),
    ]:
        val = run_cmd(f"adb -s {dev_id} shell {cmd}").strip()
        console.print(f"  [bold]{label}:[/bold] {val or '?'}")

def _action_install_apk_from_pc(dev_id):
    path = Prompt.ask("Path to APK on PC")
    if not path: return
    path = os.path.expanduser(path)
    if not os.path.exists(path): console.print(f"[red]❌ Not found: {path}[/red]"); return
    console.print(f"[yellow]📦 Installing {os.path.basename(path)}...[/yellow]")
    result = run_cmd(f'adb -s {dev_id} install -r "{path}"')
    console.print("[green]✅ Installed[/green]" if "Success" in result else f"[red]❌ {result.strip()[:200]}[/red]")

# ── File Management ────────────────────────────────────────────────────────
def _action_push_file(dev_id):
    local = Prompt.ask("Local file path")
    if not local: return
    local = os.path.expanduser(local)
    if not os.path.exists(local): console.print(f"[red]❌ Not found: {local}[/red]"); return
    remote = Prompt.ask("Destination on device", default="/sdcard/")
    console.print("[yellow]📤 Pushing...[/yellow]")
    result = run_cmd(f'adb -s {dev_id} push "{local}" "{remote}"')
    console.print("[green]✅ Pushed[/green]" if "pushed" in result else f"[dim]{result.strip()[:200]}[/dim]")

def _action_pull_file(dev_id):
    remote = Prompt.ask("File path on device (e.g. /sdcard/photo.jpg)")
    if not remote: return
    local = Prompt.ask("Save to (local path)", default=os.path.expanduser("~/Desktop/"))
    console.print("[yellow]📥 Pulling...[/yellow]")
    result = run_cmd(f'adb -s {dev_id} pull "{remote}" "{local}"')
    console.print("[green]✅ Pulled[/green]" if "pulled" in result else f"[dim]{result.strip()[:200]}[/dim]")

def _action_browse_storage(dev_id):
    path = "/sdcard/"
    while True:
        console.print(f"\n[cyan]📁 {path}[/cyan]")
        result = run_cmd(f'adb -s {dev_id} shell ls -1a "{path}" 2>/dev/null')
        entries = [e for e in result.splitlines() if e.strip() and e not in (".", "..")]
        dirs = set()
        for line in run_cmd(f'adb -s {dev_id} shell ls -d {path}*/ 2>/dev/null').splitlines():
            d = line.strip().rstrip("/").split("/")[-1]
            if d: dirs.add(d)
        for i, name in enumerate(entries[:30], 1):
            icon = "📁" if name in dirs else "📄"
            console.print(f"  [cyan]{i:>2}[/cyan]. {icon} {name}")
        if len(entries) > 30: console.print(f"  [dim]... {len(entries) - 30} more[/dim]")
        choice = Prompt.ask("[pick # to open, path to jump, q=back]", default="q")
        if choice == "q": return
        elif choice == "..": path = os.path.dirname(path.rstrip("/")) + "/"
        elif choice.isdigit() and 1 <= int(choice) <= len(entries):
            name = entries[int(choice) - 1]
            if name in dirs: path = f"{path.rstrip('/')}/{name}/"
            else:
                local = Prompt.ask(f"Pull {name} to", default=os.path.expanduser("~/Desktop/"))
                run_cmd(f'adb -s {dev_id} pull "{path}{name}" "{local}"')
                console.print(f"[green]✅ Pulled {name}[/green]")
        elif choice.startswith("/"): path = choice if choice.endswith("/") else choice + "/"

# ── Device Control ─────────────────────────────────────────────────────────
def _action_reboot_menu(dev_id):
    console.print("\n[bold]Reboot Options:[/bold]")
    console.print("  [cyan]1[/cyan]. Normal  [cyan]2[/cyan]. Recovery  [cyan]3[/cyan]. Bootloader  [cyan]4[/cyan]. Shutdown")
    choice = Prompt.ask("Pick", default="1")
    cmds = {"1": "reboot", "2": "reboot recovery", "3": "reboot bootloader", "4": "shell reboot -p"}
    labels = {"1": "Rebooting", "2": "Rebooting to recovery", "3": "Rebooting to bootloader", "4": "Shutting down"}
    if choice in cmds and Confirm.ask(f"[red]{labels[choice]}?[/red]"):
        run_cmd(f"adb -s {dev_id} {cmds[choice]}")
        console.print(f"[green]✅ {labels[choice]}...[/green]")

def _action_toggle_wifi(dev_id):
    state = run_cmd(f"adb -s {dev_id} shell settings get global wifi_on").strip()
    run_cmd(f"adb -s {dev_id} shell svc wifi {'disable' if state == '1' else 'enable'}")
    console.print(f"[green]✅ WiFi {'disabled' if state == '1' else 'enabled'}[/green]")

def _action_toggle_data(dev_id):
    state = run_cmd(f"adb -s {dev_id} shell settings get global mobile_data").strip()
    run_cmd(f"adb -s {dev_id} shell svc data {'disable' if state == '1' else 'enable'}")
    console.print(f"[green]✅ Mobile data {'disabled' if state == '1' else 'enabled'}[/green]")

def _action_toggle_bluetooth(dev_id):
    state = run_cmd(f"adb -s {dev_id} shell settings get global bluetooth_on").strip()
    run_cmd(f"adb -s {dev_id} shell svc bluetooth {'disable' if state == '1' else 'enable'}")
    console.print(f"[green]✅ Bluetooth {'disabled' if state == '1' else 'enabled'}[/green]")

def _action_volume_control(dev_id):
    console.print("\n[bold]Volume:[/bold]  [cyan]1[/cyan] Up  [cyan]2[/cyan] Down  [cyan]3[/cyan] Mute  [cyan]4[/cyan] Unmute")
    choice = Prompt.ask("Pick", default="1")
    keymap = {"1": "KEYCODE_VOLUME_UP", "2": "KEYCODE_VOLUME_DOWN", "3": "KEYCODE_VOLUME_MUTE", "4": "KEYCODE_VOLUME_UP"}
    if choice in keymap:
        run_cmd(f"adb -s {dev_id} shell input keyevent {keymap[choice]}")
        console.print("[green]✅ Done[/green]")

def _action_brightness_control(dev_id):
    current = run_cmd(f"adb -s {dev_id} shell settings get system screen_brightness").strip()
    console.print(f"[dim]Current: {current} (0-255)[/dim]")
    level = Prompt.ask("Brightness (0-255)", default=current)
    if level.isdigit() and 0 <= int(level) <= 255:
        run_cmd(f"adb -s {dev_id} shell settings put system screen_brightness {level}")
        console.print(f"[green]✅ Brightness → {level}[/green]")

def _action_interactive_shell(dev_id):
    console.print("[cyan]🖥  Entering ADB shell... (type 'exit' to return)[/cyan]")
    os.system(f"adb -s {dev_id} shell")

# ── Dev Tools ──────────────────────────────────────────────────────────────
def _action_device_info_dashboard(dev_id):
    console.print(Panel("[bold bright_white]📊 DEVICE INFO DASHBOARD[/bold bright_white]", box=box.HEAVY, border_style="bright_blue"))
    props = {
        "Model": "getprop ro.product.model", "Brand": "getprop ro.product.brand",
        "Android": "getprop ro.build.version.release", "SDK": "getprop ro.build.version.sdk",
        "Kernel": "uname -r", "Serial": "getprop ro.serialno",
        "Build": "getprop ro.build.display.id",
        "IP": "ip route | grep src | awk '{print $9}'",
    }
    table = Table(box=box.ROUNDED, border_style="dim blue", show_header=False)
    table.add_column("Property", style="bold bright_white")
    table.add_column("Value", style="bright_cyan")
    for k, cmd in props.items():
        table.add_row(k, run_cmd(f"adb -s {dev_id} shell {cmd}").strip() or "?")
    console.print(table)

def _action_battery_info(dev_id):
    console.print(Panel("[bold bright_white]🔋 BATTERY DETAILS[/bold bright_white]", box=box.HEAVY, border_style="bright_green"))
    result = run_cmd(f"adb -s {dev_id} shell dumpsys battery")
    table = Table(box=box.ROUNDED, border_style="dim green", show_header=False)
    table.add_column("Property", style="bold bright_white")
    table.add_column("Value", style="bright_green")
    for line in result.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() and v.strip(): table.add_row(k.strip(), v.strip())
    console.print(table)

def _action_network_info(dev_id):
    console.print(Panel("[bold bright_white]🌐 NETWORK INFO[/bold bright_white]", box=box.HEAVY, border_style="bright_cyan"))
    info = {
        "WiFi IP": "ip route | grep src | awk '{print $9}'",
        "WiFi SSID": 'dumpsys wifi | grep "mWifiInfo" | grep -o "SSID: [^,]*" | head -1',
        "WiFi Signal": 'dumpsys wifi | grep "mWifiInfo" | grep -o "RSSI: [^,]*" | head -1',
        "MAC": "cat /sys/class/net/wlan0/address 2>/dev/null",
    }
    table = Table(box=box.ROUNDED, border_style="dim cyan", show_header=False)
    table.add_column("Property", style="bold bright_white")
    table.add_column("Value", style="bright_cyan")
    for k, cmd in info.items():
        table.add_row(k, run_cmd(f"adb -s {dev_id} shell {cmd}").strip() or "—")
    console.print(table)

def _action_storage_info(dev_id):
    console.print(Panel("[bold bright_white]💾 STORAGE BREAKDOWN[/bold bright_white]", box=box.HEAVY, border_style="bright_yellow"))
    result = run_cmd(f"adb -s {dev_id} shell df -h")
    table = Table(box=box.ROUNDED, border_style="dim yellow", show_header=True, header_style="bold bright_yellow")
    for col in ["Filesystem", "Size", "Used", "Avail", "Use%", "Mount"]:
        table.add_column(col)
    for line in result.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 6: table.add_row(*parts[:6])
    console.print(table)

def _action_running_processes(dev_id):
    console.print(Panel("[bold bright_white]⚙️  TOP PROCESSES[/bold bright_white]", box=box.HEAVY, border_style="bright_magenta"))
    result = run_cmd(f"adb -s {dev_id} shell top -n 1 -b | head -25")
    for line in result.splitlines():
        console.print(f"  [dim]{line}[/dim]")

def _action_send_notification(dev_id):
    title = Prompt.ask("Title", default="Fenox Alert")
    body = Prompt.ask("Body", default="Test from fenox")
    run_cmd(f'adb -s {dev_id} shell "cmd notification post -S bigtext -t \'{title}\' fenox_tag \'{body}\'" 2>/dev/null')
    console.print(f"[green]✅ Notification sent: {title}[/green]")

def _action_read_notifications(dev_id):
    console.print("[cyan]📋 Recent notifications:[/cyan]")
    result = run_cmd(f"adb -s {dev_id} shell dumpsys notification --noredact 2>/dev/null | grep -E 'pkg=|title=|text=' | head -30")
    for line in result.splitlines():
        console.print(f"  [dim]{line.strip()[:120]}[/dim]")
    if not result.strip(): console.print("[dim]  No notifications found[/dim]")

def _action_health_monitor(dev_id):
    """Real-time device health monitor with auto-refresh."""
    console.print("[cyan]🏥 Device Health Monitor — Press [bold]Ctrl+C[/bold] to exit[/cyan]")
    time.sleep(0.5)

    def _get_bat_temp():
        for line in run_cmd(f"adb -s {dev_id} shell dumpsys battery").splitlines():
            if "temperature" in line.lower():
                try: return f"{int(line.split(':')[1].strip()) / 10.0}°C"
                except: pass
        return "?"

    def _get_mem():
        info = run_cmd(f"adb -s {dev_id} shell cat /proc/meminfo | head -3")
        total = avail = 0
        for line in info.splitlines():
            if "MemTotal" in line:
                try: total = int(line.split(":")[1].strip().split()[0])
                except: pass
            elif "MemAvailable" in line:
                try: avail = int(line.split(":")[1].strip().split()[0])
                except: pass
        if total > 0:
            used = total - avail
            pct = int(used * 100 / total)
            return f"{used // 1024}MB / {total // 1024}MB", pct
        return "?", 0

    def _get_net():
        ip = run_cmd(f"adb -s {dev_id} shell ip route | grep src | awk '{{print $9}}'").strip()
        ssid = run_cmd(f'adb -s {dev_id} shell dumpsys wifi | grep "mWifiInfo" | grep -o "SSID: [^,]*" | head -1').strip()
        sig = run_cmd(f'adb -s {dev_id} shell dumpsys wifi | grep "mWifiInfo" | grep -o "RSSI: [^,]*" | head -1').strip()
        return ssid or "—", ip or "—", sig or "—"

    def _build():
        tele = get_device_telemetry(dev_id, force=True)
        bat = str(tele.get("battery", "?"))
        charging = tele.get("charging", False)
        try: bat_pct = int(bat)
        except: bat_pct = 0
        bat_bar = _bar(bat_pct, 24)
        screen = tele.get("screen", "?")
        android = tele.get("android", "?")
        storage = tele.get("storage", "?")
        fg_app = tele.get("app", "?")
        bat_temp = _get_bat_temp()
        mem_str, mem_pct = _get_mem()
        mem_bar = _bar(mem_pct, 24)
        ssid, wip, signal = _get_net()
        now = datetime.datetime.now().strftime("%H:%M:%S")
        # Temperature color
        try:
            temp_val = float(bat_temp.replace("°C", ""))
            if temp_val > 40: temp_color = "red"
            elif temp_val > 32: temp_color = "yellow"
            else: temp_color = "green"
        except: temp_color = "white"
        content = Text.from_markup(
            f"[bold bright_white]❤️  LIVE HEALTH MONITOR[/bold bright_white]  [dim]│  refreshed {now}[/dim]\n"
            f"[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]\n\n"
            f"  🔋 Battery    {bat_bar}  {'⚡ Charging' if charging else ''}\n"
            f"  🌡️  Temp       [{temp_color}]{bat_temp}[/{temp_color}]\n\n"
            f"  💾 Storage    [bright_white]{storage}[/bright_white]\n"
            f"  🧠 Memory     {mem_bar}  [dim]{mem_str}[/dim]\n\n"
            f"  📱 Screen     [bright_white]{screen}[/bright_white]\n"
            f"  📲 Foreground [bright_white]{fg_app}[/bright_white]\n\n"
            f"  🌐 WiFi       [bright_white]{ssid}[/bright_white]  [dim]({wip})[/dim]  [dim]{signal}[/dim]\n"
            f"  🤖 Android    [bright_white]{android}[/bright_white]\n"
        )
        return Panel(content, box=box.HEAVY, border_style="bright_green", padding=(0, 2))

    try:
        with Live(_build(), console=console, refresh_per_second=1, screen=False) as live:
            while True:
                time.sleep(3)
                live.update(_build())
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/dim]")

# ═══════════════════════════════════════════════════════════════════════════
#  CATEGORY SUB-MENUS
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
#  PHONE DATA — the phone's own data, read through its content providers
#
#  The adb `shell` user is granted READ_SMS, READ_CALL_LOG, READ_CONTACTS and
#  READ_CALENDAR, so messages, call history, contacts and calendar can be read
#  over adb with no root and nothing installed on the phone. Writing works where
#  the matching WRITE_ permission is granted — marking a thread read, clearing a
#  call log entry — and everything here reports a refusal instead of showing an
#  empty list, because "no messages" and "not allowed to look" are very different
#  things to be told.
# ═══════════════════════════════════════════════════════════════════════════

CONTENT_ROW = re.compile(r"^Row:\s*\d+\s*(.*)$")
CONTENT_FIELD = re.compile(r",\s+(?=[A-Za-z_][A-Za-z0-9_]*=)")


def adb_shell(dev_id, shell_cmd, timeout=40):
    """(ok, output) for a shell command on one device, with its errors.

    Unlike run_cmd this reports failure: a provider that refuses access has to be
    visible, not swallowed into output that then reads as an empty inbox.
    """
    try:
        # A list, not shell=True: the local shell would strip the quotes meant for
        # the device shell (--sort 'date DESC' became --sort date DESC, so the
        # device printed its usage text and a full inbox read as empty), and it
        # would let a message body's content reach the local shell at all.
        proc = subprocess.run(["adb", "-s", dev_id, "shell", shell_cmd],
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (proc.stdout + proc.stderr).strip()
    return (proc.returncode == 0 and not content_error(output)), output


def content_error(output):
    """The provider's own complaint when a query was refused, else ''.

    A refusal is checked for first and across the whole output: the provider
    prints a generic "Error while accessing provider" line *before* the
    SecurityException that explains it, and the explanation is the useful half.
    """
    if "Permission Denial" in output or "SecurityException" in output:
        return "permission denied — this ROM restricts what the shell user may read"
    for line in output.splitlines():
        if line.startswith("usage:") or "unknown subcommand" in line:
            # A command the device did not understand must never look like "no data".
            return f"the phone rejected the command: {line.strip()[:120]}"
        for marker in ("Error while accessing provider", "Unknown URI",
                       "no such column", "IllegalArgumentException"):
            if marker in line:
                return line.strip()[:200]
    return ""


def parse_content_rows(output):
    """Rows from `content query`, as dicts.

    The format is `Row: <n> column=value, column=value`. A value may itself contain
    ", " — a message body, a contact's note — so a comma only starts a new column
    when what follows looks like `column=`. A value containing a newline spills onto
    the following line, which is folded back into that column.
    """
    rows = []
    for raw in output.splitlines():
        line = raw.strip()
        match = CONTENT_ROW.match(line)
        if not match:
            # Anything else (a wrapped value, the CLI's trailing "Date:" line) is
            # either a continuation or noise. Only a value can continue a row.
            if rows and line and not line.startswith("Date:") and "=" not in line:
                last = rows[-1]
                key = next(reversed(last), None)
                if key:
                    last[key] = f"{last[key]}\n{line}"
            continue
        row = {}
        for field in CONTENT_FIELD.split(match.group(1)):
            if "=" in field:
                name, value = field.split("=", 1)
                row[name.strip()] = value
        rows.append(row)
    return rows


def content_query(dev_id, uri, projection=None, where=None, sort=None):
    """(ok, rows, error) for one provider query on the device."""
    cmd = f"content query --uri {uri}"
    if projection:
        cmd += f" --projection {':'.join(projection)}"
    if where:
        cmd += f" --where {shlex.quote(where)}"
    if sort:
        cmd += f" --sort {shlex.quote(sort)}"
    ok, output = adb_shell(dev_id, cmd)
    if not ok:
        return False, [], content_error(output) or output[:200]
    return True, parse_content_rows(output), ""


def phone_contacts(dev_id):
    """{digits: contact name} so numbers can be shown as the person they are."""
    ok, rows, _ = content_query(dev_id, CONTACT_PHONES_URI,
                                ["display_name", "data1"])
    names = {}
    for row in rows if ok else []:
        digits = re.sub(r"\D", "", row.get("data1", ""))
        name = (row.get("display_name") or "").strip()
        if name and name != "(Unknown)" and digits:
            names.setdefault(_number_key(digits), name)
    return names


def _number_key(digits):
    """Match numbers by their last nine digits: the country code may be recorded
    one way in the call log and another way in contacts."""
    return digits[-9:] if len(digits) >= 9 else digits


def number_label(number, names, redact=False):
    """A phone number as its contact name where we can, redacted on request."""
    digits = re.sub(r"\D", "", number or "")
    if redact:
        return f"…{digits[-4:]}" if len(digits) > 4 else "…"
    if not digits:
        return number or "unknown"
    name = names.get(_number_key(digits))
    if name and name != number:
        return f"{name} ({number})"
    return number


def _fmt_when(ms):
    """An epoch-millisecond timestamp the way a person reads it."""
    try:
        when = datetime.datetime.fromtimestamp(int(ms) / 1000)
    except (TypeError, ValueError, OSError):
        return "—"
    now = datetime.datetime.now()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%d %b %H:%M")
    return when.strftime("%d %b %Y")


def phone_threads(dev_id, names=None, unread_only=False, limit=None):
    """(threads, error) — newest first, each with address, date and unread count.

    Three queries: the grouped conversation list carries each thread's message
    count and last snippet, a date-sorted pass over the messages supplies the
    address and timestamp per thread, and an inbox pass counts the unread ones.
    """
    names = names if names is not None else {}
    ok, grouped, error = content_query(dev_id, SMS_THREADS_URI,
                                       ["thread_id", "msg_count", "snippet"])
    if not ok:
        return None, error
    ok, latest, error = content_query(dev_id, SMS_URI,
                                      ["thread_id", "address", "date"],
                                      sort="date DESC")
    if not ok:
        return None, error
    ok, unread_rows, _ = content_query(dev_id, SMS_INBOX_URI, ["thread_id"],
                                       where="read=0")
    unread = {}
    for row in unread_rows if ok else []:
        key = row.get("thread_id", "")
        unread[key] = unread.get(key, 0) + 1
    head = {}                              # newest first, so the first row per thread wins
    for row in latest:
        head.setdefault(row.get("thread_id", ""), row)
    threads = []
    for row in grouped:
        thread_id = row.get("thread_id", "")
        newest = head.get(thread_id, {})
        address = newest.get("address", "")
        threads.append({
            "thread_id": thread_id,
            "address": address,
            "label": number_label(address, names),
            "date": newest.get("date", ""),
            "when": _fmt_when(newest.get("date")),
            "count": row.get("msg_count", ""),
            "unread": unread.get(thread_id, 0),
            # A snippet can hold newlines (a bank alert, a multi-part SMS); the
            # list is one line per thread, so collapse it there.
            "snippet": " ".join(str(row.get("snippet", "")).split()),
        })
    threads.sort(key=lambda t: int(t["date"] or 0), reverse=True)
    if unread_only:
        threads = [t for t in threads if t["unread"]]
    if limit:
        threads = threads[:limit]
    return threads, ""


def phone_thread_messages(dev_id, thread_id, names=None, limit=30):
    """(messages, error) for one conversation, oldest first (the last `limit`)."""
    names = names if names is not None else {}
    try:
        clause = f"thread_id={int(thread_id)}"
    except (TypeError, ValueError):
        return None, f"not a thread id: {thread_id}"
    ok, rows, error = content_query(
        dev_id, SMS_URI, ["_id", "address", "date", "type", "read", "body"],
        where=clause, sort="date ASC")
    if not ok:
        return None, error
    messages = []
    for row in rows:
        kind = {"1": "in", "2": "out", "3": "draft", "4": "out", "5": "failed"}.get(row.get("type"), "in")
        messages.append({
            "id": row.get("_id", ""),
            "address": row.get("address", ""),
            "label": number_label(row.get("address", ""), names),
            "when": _fmt_when(row.get("date")),
            "date": row.get("date", ""),
            "direction": kind,
            "read": row.get("read", "1") == "1",
            "body": row.get("body", "") or "(empty message)",
        })
    return (messages[-limit:] if limit else messages), ""


def phone_search_messages(dev_id, text, names=None, limit=40):
    """(messages, error) — messages whose body contains `text`, newest first."""
    names = names if names is not None else {}
    safe = str(text).replace("'", "''")        # SQL string escaping
    ok, rows, error = content_query(
        dev_id, SMS_URI, ["_id", "address", "date", "type", "read", "body"],
        where=f"body LIKE '%{safe}%'", sort="date DESC")
    if not ok:
        return None, error
    messages = []
    for row in rows[:limit]:
        messages.append({
            "id": row.get("_id", ""),
            "address": row.get("address", ""),
            "label": number_label(row.get("address", ""), names),
            "when": _fmt_when(row.get("date")),
            "date": row.get("date", ""),
            "direction": "out" if row.get("type") == "2" else "in",
            "read": row.get("read", "1") == "1",
            "body": row.get("body", "") or "(empty message)",
            "thread_id": row.get("thread_id", ""),
        })
    return messages, ""


def phone_mark_thread_read(dev_id, thread_id):
    """(ok, message). Marking is a write, so it is never done silently."""
    try:
        clause = f"thread_id={int(thread_id)} AND read=0"
    except (TypeError, ValueError):
        return False, f"not a thread id: {thread_id}"
    ok, output = adb_shell(
        dev_id, f"content update --uri {SMS_URI} --where {shlex.quote(clause)} "
                f"--bind read:i:1")
    if not ok:
        return False, content_error(output) or output[:200]
    count = re.search(r"Updated:?\s*(\d+)", output)
    return True, f"marked {count.group(1) if count else 'the'} message(s) read"


def _provider_text(value):
    """A provider column as text, with its empty-value spellings as ''.

    A content provider prints an unset column as the literal word NULL, and a
    dialler writes "(Unknown)" for a number it could not match. Either would be
    shown as if it were a name — and `NULL` is exactly what a withheld number
    looks like, so it has to be blank, not the word.
    """
    text = str(value or "").strip()
    return "" if text.upper() in ("NULL", "(UNKNOWN)", "UNKNOWN") else text


def _fmt_duration(seconds):
    """How long a call lasted, the way a person reads it."""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"                       # never connected, or under a second
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def call_kind(code):
    """A provider type code as the word a person uses for it."""
    return CALL_KINDS.get(str(code or "").strip(), "call")


def calls_where(kinds=None, days=None, search=None, number=None):
    """The provider `--where` clause for a call filter, or None for everything.

    Built in one place because the write path filters with it too: a clause that
    reads the wrong rows would mark the wrong calls as seen.
    """
    clauses = []
    codes = [CALL_KIND_KEYS[kind] for kind in (kinds or []) if kind in CALL_KIND_KEYS]
    if len(codes) == 1:
        clauses.append(f"type={codes[0]}")
    elif codes:
        # Grouped: an ungrouped "type=1 OR type=2" would let a later AND bind to
        # only the second of them.
        clauses.append("(" + " OR ".join(f"type={code}" for code in codes) + ")")
    if days:
        clauses.append(f"date>={int((time.time() - int(days) * 86400) * 1000)}")
    if search:
        safe = str(search).replace("'", "''")        # SQL string escaping
        clauses.append(f"(number LIKE '%{safe}%' OR name LIKE '%{safe}%')")
    if number:
        digits = re.sub(r"\D", "", str(number))
        tail = digits[-9:] if len(digits) >= 9 else digits
        if tail:
            clauses.append(f"number LIKE '%{tail}%'")
    return " AND ".join(clauses) or None


def phone_calls(dev_id, names=None, kinds=None, days=30, search=None, number=None,
                limit=None):
    """(calls, error) — newest first, with who, when, how long and how it ended.

    `days` of 0 (or None) reads the whole log; the default window keeps a redraw
    to a few hundred rows, which the provider returns in well under a second.
    The device's own `name` column is only filled when its dialler matched the
    number to a contact, so names are resolved from contacts as messages are.
    """
    names = names if names is not None else {}
    ok, rows, error = content_query(
        dev_id, CALL_LOG_URI,
        ["_id", "number", "date", "duration", "type", "new", "name"],
        where=calls_where(kinds, days, search, number), sort="date DESC")
    if not ok:
        return None, error
    calls = []
    for row in rows:
        address = _provider_text(row.get("number"))
        cached = _provider_text(row.get("name"))
        calls.append({
            "id": row.get("_id", ""),
            "number": address,
            "label": cached if cached and cached != "(Unknown)" else number_label(address, names),
            "when": _fmt_when(row.get("date")),
            "date": row.get("date", ""),
            "kind": call_kind(row.get("type")),
            "duration": _fmt_duration(row.get("duration")),
            "new": row.get("new", "0") == "1",
        })
    return (calls[:limit] if limit else calls), ""


def phone_call_counts(calls):
    """A list of calls as a breakdown line, missed first.

    Missed leads because it is the one a person is looking for; "1 missed · 4 in ·
    2 out" says more in one line than a table of totals underneath the list.
    """
    order = ("missed", "incoming", "outgoing", "rejected", "blocked", "voicemail",
             "answered elsewhere", "call")
    words = {"incoming": "in", "outgoing": "out"}
    counts = {}
    for call in calls:
        counts[call["kind"]] = counts.get(call["kind"], 0) + 1
    return " · ".join(f"{counts[kind]} {words.get(kind, kind)}"
                      for kind in order if counts.get(kind))


def phone_mark_calls_seen(dev_id, call_ids):
    """(ok, message) — clear the "new call" flag on the rows shown.

    A write, so it only ever happens on request. The device prints nothing at all
    when a clause matches no rows, so the result is confirmed by reading the flag
    back instead of trusting a line of output that may not be there.
    """
    ids = [str(i) for i in call_ids if str(i).strip().isdigit()]
    if not ids:
        return False, "no calls to mark"
    clause = f"_id IN ({','.join(ids)})"
    ok, output = adb_shell(
        dev_id, f"content update --uri {CALL_LOG_URI} --where {shlex.quote(clause)} "
                f"--bind new:i:0")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(dev_id, CALL_LOG_URI, ["_id", "new"], where=clause)
    marked = len(ids)                       # the device said nothing: assume it worked
    if ok:
        marked = sum(1 for row in rows if row.get("new") != "1")
    return True, f"marked {marked} of {len(ids)} call(s) as seen"


def phone_contact_rows(dev_id, search=None, limit=None):
    """(contacts, error) — one row per phone number, by name.

    The contacts `data/phones` view already joins numbers onto names, so a person
    with three numbers is three rows, each carrying their name. Sorted by the
    device (name ASC), which is also how its own app shows them.
    """
    where = None
    if search:
        safe = str(search).replace("'", "''")
        where = (f"(display_name LIKE '%{safe}%' OR data1 LIKE '%{safe}%')")
    ok, rows, error = content_query(
        dev_id, CONTACT_PHONES_URI,
        ["contact_id", "display_name", "data1"],
        where=where, sort="display_name ASC")
    if not ok:
        return None, error
    seen, contacts = set(), []
    for row in rows:
        name = _provider_text(row.get("display_name"))
        number = _provider_text(row.get("data1"))
        if not number:
            continue
        key = (name.lower(), re.sub(r"\D", "", number))
        if key in seen:
            continue
        seen.add(key)
        contacts.append({
            "id": row.get("contact_id", ""),
            "name": name or "(no name)",
            "number": number,
            "type": _number_type(row.get("data2")),
        })
    return (contacts[:limit] if limit else contacts), ""


def _number_type(code):
    """A Phone.TYPE code as a short label, '' when unset."""
    return {"1": "home", "2": "mobile", "3": "work"}.get(str(code or "").strip(), "")


def phone_calendars(dev_id):
    """(calendars, error) — the accounts the phone keeps events in."""
    ok, rows, error = content_query(
        dev_id, CALENDAR_URI, ["_id", "name", "account_name", "ownerAccount",
                               "account_type"])
    if not ok:
        return None, error
    calendars = []
    for row in rows:
        name = (_provider_text(row.get("calendar_displayName"))
                or _provider_text(row.get("name"))
                or _provider_text(row.get("account_name"))
                or f"calendar {row.get('_id', '?')}")
        calendars.append({
            "id": row.get("_id", ""),
            "name": name,
            "account": _provider_text(row.get("account_name"))
                       or _provider_text(row.get("ownerAccount")),
            "local": _provider_text(row.get("account_type")).lower() == "local",
        })
    return calendars, ""


def phone_events(dev_id, days=7, calendar_id=None, search=None, limit=None):
    """(events, error) — occurrences between now and `days` ahead, soonest first.

    Read from the *instances* table, not the events table: instances are the
    expanded occurrences, so a weekly repeating event shows up every week it
    actually happens instead of once at its original date.
    """
    start = int(time.time() * 1000)
    end = start + int(days or 0) * 86400_000
    ok, rows, error = content_query(
        dev_id, CALENDAR_INSTANCES_URI.format(start=start, end=end),
        ["event_id", "title", "begin", "end", "allDay", "eventLocation",
         "calendar_id"], sort="begin ASC")
    if not ok:
        return None, error
    events = []
    for row in rows:
        title = _provider_text(row.get("title")) or "(untitled)"
        if search and str(search).lower() not in title.lower() \
                and str(search).lower() not in _provider_text(row.get("eventLocation")).lower():
            continue
        if calendar_id and row.get("calendar_id") != str(calendar_id):
            continue
        events.append({
            "id": row.get("event_id", ""),
            "title": title,
            "when": _fmt_when(row.get("begin")),
            "begin": row.get("begin", ""),
            "end": row.get("end", ""),
            "all_day": row.get("allDay", "0") == "1",
            "where": _provider_text(row.get("eventLocation")),
            "calendar_id": row.get("calendar_id", ""),
        })
    return (events[:limit] if limit else events), ""


def phone_add_event(dev_id, title, begin_ms, end_ms, calendar_id=1):
    """(ok, message) — put one event on the phone. A write, so never implicit."""
    title = str(title or "").strip()
    if not title:
        return False, "the event needs a title"
    try:
        begin_ms, end_ms = int(begin_ms), int(end_ms)
    except (TypeError, ValueError):
        return False, "start and end must be timestamps in milliseconds"
    if end_ms <= begin_ms:
        return False, "the end must come after the start"
    ok, output = adb_shell(
        dev_id,
        f"content insert --uri {CALENDAR_EVENTS_URI} "
        f"--bind title:s:{shlex.quote(title)} "
        f"--bind dtstart:l:{begin_ms} --bind dtend:l:{end_ms} "
        f"--bind eventTimezone:s:UTC --bind calendar_id:i:{int(calendar_id)}")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(
        dev_id, CALENDAR_EVENTS_URI, ["_id"],
        where=f"title={shlex.quote(title)} AND dtstart={begin_ms}")
    if ok and rows:
        return True, f"added '{title}' to the phone's calendar"
    return True, f"added '{title}' (not verified on the phone)"


def phone_delete_call(dev_id, call_id):
    """(ok, message) — remove one call from the phone's log. Irreversible."""
    try:
        call_id = int(str(call_id).strip())
    except (TypeError, ValueError):
        return False, "not a call id"
    ok, output = adb_shell(
        dev_id, f"content delete --uri {CALL_LOG_URI} --where {shlex.quote(f'_id={call_id}')}")
    if not ok:
        return False, content_error(output) or output[:200]
    ok, rows, _ = content_query(dev_id, CALL_LOG_URI, ["_id"], where=f"_id={call_id}")
    if ok:
        return (not rows), ("removed from the phone's call log" if not rows
                            else "the phone still lists the call — it may refuse deletes")
    return True, "delete sent (could not verify)"


def _provider_count(dev_id, uri, where):
    """Row count for one provider query, or None when the provider refuses.

    The call screen's summary counts unread messages and unheard voicemails; a
    ROM that refuses one of them shows a dash there rather than zero, which
    would read as "all clear".
    """
    ok, rows, _ = content_query(dev_id, uri, ["_id"], where=where)
    return len(rows) if ok else None


def _day_label(ms):
    """Which heading a call sits under: today, yesterday, or the weekday."""
    try:
        when = datetime.datetime.fromtimestamp(int(ms) / 1000)
    except (TypeError, ValueError, OSError):
        return "EARLIER"
    today = datetime.date.today()
    if when.date() == today:
        return "TODAY"
    if when.date() == today - datetime.timedelta(days=1):
        return "YESTERDAY"
    return when.strftime("%A %d %b").upper()


def resolve_phone_device(alias=None):
    """The device to read from: a named one, an adb id, or the only one online."""
    if alias:
        if alias in DEVICES:
            target = check_and_connect(alias, interactive=True)
            if not target:
                console.print(f"[red]❌ {alias} is not reachable — run Doctor, or pair it again.[/red]")
            return target
        return alias                       # an adb id or ip:port
    connected = get_connected_device_ids()
    if not connected:
        console.print("[red]❌ No device is connected. Plug one in, or run [bold]fenox pair[/bold].[/red]")
        return None
    if len(connected) > 1:
        console.print("[yellow]More than one device is connected — pass [bold]--device <alias>[/bold]:[/yellow]")
        for dev_id in connected:
            console.print(f"  [dim]·[/dim] {dev_id}")
        return None
    return connected[0]


def _phone_refused(what, error):
    """Say exactly why nothing was shown, instead of showing nothing."""
    console.print(Panel(
        f"[yellow]The phone would not share its {what}.[/yellow]\n\n"
        f"[dim]{error}[/dim]\n\n"
        "[dim]The phone must have USB debugging on, and be unlocked once after "
        "plugging in. Some ROMs also restrict what the adb shell user may read.[/dim]",
        box=box.ROUNDED, border_style="yellow",
        title=Text("CANNOT READ", style="yellow"), title_align="left", padding=(0, 1)))


def _redact_body(body):
    """Hide the words but keep the shape, so activity is still visible."""
    return f"[{len(body)} characters hidden]"


def print_message_threads(dev_id, args):
    """Render the message thread list for the CLI."""
    names = phone_contacts(dev_id)
    redact = getattr(args, "redact", False)
    threads, error = phone_threads(dev_id, names=names,
                                   unread_only=getattr(args, "unread", False),
                                   limit=getattr(args, "limit", None) or 25)
    if error:
        _phone_refused("messages", error)
        return False
    if getattr(args, "json_out", False):
        print(json.dumps({"threads": [_public_thread(t, redact) for t in threads]}, indent=2))
        return True
    if not threads:
        console.print("[yellow]No message threads to show.[/yellow]")
        return True
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold bright_cyan", pad_edge=False)
    table.add_column("Thread", justify="right", no_wrap=True, style="dim")
    table.add_column("From", no_wrap=True, max_width=26)
    table.add_column("When", no_wrap=True, style="dim")
    table.add_column("Msgs", justify="right", style="dim")
    table.add_column("Unread", justify="right")
    table.add_column("Last message", overflow="ellipsis", no_wrap=True)
    for thread in threads:
        body = _redact_body(thread["snippet"]) if redact else thread["snippet"]
        label = (f"…{re.sub(r'\\D', '', thread['address'])[-4:]}" if redact
                 else thread["label"])
        table.add_row(str(thread["thread_id"]), label, thread["when"], thread["count"],
                      f"[bold yellow]{thread['unread']}[/bold yellow]" if thread["unread"] else "",
                      f"[dim]{body}[/dim]")
    console.print(table)
    total_unread = sum(t["unread"] for t in threads)
    console.print(f"[dim]{len(threads)} thread(s)"
                  + (f" · {total_unread} unread" if total_unread else "") + "[/dim]")
    return True


def render_transcript(messages, key=None, redact=False):
    """Print one conversation oldest-first, as a compact table."""
    if not messages:
        console.print("[yellow]No messages in this thread.[/yellow]")
        return
    table = Table(box=box.SIMPLE, header_style="bold bright_cyan", pad_edge=False)
    table.add_column("When", no_wrap=True, style="dim")
    table.add_column("Who", no_wrap=True, max_width=24)
    table.add_column("#", justify="right", no_wrap=True, style="dim")
    table.add_column("Message", overflow="fold")
    for index, message in enumerate(messages, start=1):
        arrow = "◀" if message["direction"] == "in" else "▶"
        colour = "green" if message["direction"] == "in" else "cyan"
        who = number_label(message["address"], key or {}, redact=redact)
        body = _redact_body(message["body"]) if redact else message["body"]
        unread = "" if message["read"] else "[bold yellow]•[/bold yellow] "
        table.add_row(message["when"], f"[{colour}]{arrow}[/{colour}] {who}",
                      str(index), f"{unread}{body}")
    console.print(table)


def export_transcript(path, messages, title, redact=False):
    """Write a conversation to a file as plain text. Local only, never uploaded."""
    target = os.path.expanduser(path)
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"{title}\n" + "=" * len(title) + "\n\n")
            for message in messages:
                who = "me" if message["direction"] == "out" else "them"
                body = _redact_body(message["body"]) if redact else message["body"]
                f.write(f"[{message['when']}] {who}: {body}\n")
    except OSError as exc:
        console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
        return
    console.print(f"[green]✅ Exported {len(messages)} message(s) to {_pretty_path(target)}[/green]")


def print_messages(dev_id, args):
    """CLI rendering for the messages resource: a thread, a search, or the list."""
    names = phone_contacts(dev_id)
    redact = getattr(args, "redact", False)
    limit = getattr(args, "limit", None) or 25
    thread_id = getattr(args, "thread", None)
    if thread_id:
        messages, error = phone_thread_messages(dev_id, thread_id, names=names, limit=limit)
        if error:
            _phone_refused("messages", error)
            return
        if getattr(args, "json_out", False):
            print(json.dumps({"thread_id": thread_id,
                              "messages": [_public_message(m, redact) for m in messages]}, indent=2))
        else:
            render_transcript(messages, names, redact)
        if getattr(args, "export", None):
            export_transcript(args.export, messages, f"Thread {thread_id}", redact)
        if getattr(args, "mark_read", False):
            ok, note = phone_mark_thread_read(dev_id, thread_id)
            console.print(f"[{'green]✅' if ok else 'red]❌'} {note}[/]")
        return
    query = getattr(args, "search", None)
    if query:
        messages, error = phone_search_messages(dev_id, query, names=names, limit=limit)
        if error:
            _phone_refused("messages", error)
            return
        if getattr(args, "json_out", False):
            print(json.dumps({"search": query,
                              "messages": [_public_message(m, redact) for m in messages]}, indent=2))
            return
        if not messages:
            console.print(f"[yellow]No messages match '{query}'.[/yellow]")
            return
        console.print(f"[dim]{len(messages)} message(s) matching[/dim] [bold]{query}[/bold]\n")
        render_transcript(list(reversed(messages)), names, redact)
        return
    print_message_threads(dev_id, args)


def _public_message(message, redact=False):
    """A message as JSON, with the personal fields redacted on request."""
    return {
        "id": message["id"],
        "from": "…" if redact else message["address"],
        "label": "…" if redact else message["label"],
        "when": message["when"],
        "direction": message["direction"],
        "read": message["read"],
        "body": _redact_body(message["body"]) if redact else message["body"],
    }


# One mark and colour per call outcome, shared by the CLI table and the screens.
CALL_MARKS = {"missed": ("✆", "red"), "incoming": ("↙", "green"),
              "outgoing": ("↗", "cyan"), "rejected": ("⊘", "yellow"),
              "blocked": ("⊘", "red"), "voicemail": ("✉", "bright_black"),
              "answered elsewhere": ("↔", "bright_black"),
              "call": ("·", "bright_black")}

CALL_COLOURS = {kind: colour for kind, (_, colour) in CALL_MARKS.items()}


def render_calls(calls, redact=False):
    """Print a call list as a compact table, newest first."""
    if not calls:
        console.print("[yellow]No calls to show.[/yellow]")
        return
    table = Table(box=box.SIMPLE, header_style="bold bright_cyan", pad_edge=False)
    table.add_column("", no_wrap=True)
    table.add_column("Who", no_wrap=True, max_width=26)
    table.add_column("When", no_wrap=True, style="dim")
    table.add_column("Length", justify="right", no_wrap=True, style="dim")
    table.add_column("Outcome", no_wrap=True)
    for call in calls:
        mark, colour = CALL_MARKS.get(call["kind"], CALL_MARKS["call"])
        who = number_label(call["number"], {}, redact=redact)
        table.add_row(f"[{colour}]{mark}[/{colour}]", who, call["when"],
                      call["duration"],
                      f"[{colour}]{call['kind']}[/{colour}]"
                      + (" [bold yellow]new[/bold yellow]" if call["new"] else ""))
    console.print(table)


def export_calls(path, calls, redact=False):
    """Write a call list to a file as plain text. Local only, never uploaded."""
    target = os.path.expanduser(path)
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write("Fenox call log\n" + "=" * 14 + "\n\n")
            for call in calls:
                who = number_label(call["number"], {}, redact=redact)
                f.write(f"[{call['when']}] {call['kind']:<17} {who} ({call['duration']})\n")
    except OSError as exc:
        console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
        return
    console.print(f"[green]✅ Exported {len(calls)} call(s) to {_pretty_path(target)}[/green]")


def print_calls(dev_id, args):
    """CLI rendering for the call log: recent, missed, or one number's history."""
    names = phone_contacts(dev_id)
    redact = getattr(args, "redact", False)
    kinds = [kind for kind in ("missed", "incoming", "outgoing")
             if getattr(args, kind, False)]
    number = getattr(args, "from_number", None)
    days = getattr(args, "days", 30)
    calls, error = phone_calls(dev_id, names=names, kinds=kinds or None, days=days,
                               search=getattr(args, "search", None), number=number,
                               limit=getattr(args, "limit", None) or 25)
    if error:
        _phone_refused("call log", error)
        return False
    if getattr(args, "dial", False):
        if not number:
            console.print("[yellow]--dial needs --from <number> — it has to know who "
                          "to call.[/yellow]")
            return False
        _call_number(dev_id, number)
        return True
    if getattr(args, "json_out", False):
        print(json.dumps({"calls": [_public_call(c, redact) for c in calls]}, indent=2))
        return True
    if not calls:
        console.print(f"[yellow]No calls in the last {days} day(s).[/yellow]" if days
                      else "[yellow]No calls to show.[/yellow]")
        return True
    if number:
        console.print(f"[dim]History with[/dim] "
                      f"[bold]{number_label(number, names, redact=redact)}[/bold]\n")
    render_calls(calls, redact)
    console.print(f"[dim]{len(calls)} call(s) · {phone_call_counts(calls)}"
                  + (f" · last {days} days" if days else "") + "[/dim]")
    if getattr(args, "export", None):
        export_calls(args.export, calls, redact)
    if getattr(args, "mark_read", False):
        ok, note = phone_mark_calls_seen(dev_id, [c["id"] for c in calls])
        console.print(f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'} {note}[/]")
    return True


def _public_call(call, redact=False):
    """A call as JSON, with the personal fields redacted on request."""
    return {
        "id": call["id"],
        "number": "…" if redact else call["number"],
        "label": "…" if redact else call["label"],
        "when": call["when"],
        "kind": call["kind"],
        "duration": call["duration"],
        "new": call["new"],
    }


def _call_number(dev_id, number):
    """Place a call from the terminal. The shell user holds CALL_PHONE."""
    digits = re.sub(r"[^\d+#*]", "", number or "")
    if not digits:
        console.print("[yellow]No number to call.[/yellow]")
        return
    if not Confirm.ask(f"[bold]Call {number}?[/bold] It dials on the phone now.", default=False):
        return
    # ACTION_CALL places the call, ACTION_DIAL only fills the dialler. The shell
    # user is allowed CALL, but a few ROMs refuse it for background starts, so the
    # dialler plus the call key is the fallback.
    ok, _ = adb_shell(dev_id, f"am start -a android.intent.action.CALL -d tel:{digits}")
    if not ok:
        adb_shell(dev_id, f"am start -a android.intent.action.DIAL -d tel:{digits}")
        time.sleep(1)
        adb_shell(dev_id, "input keyevent KEYCODE_CALL")
    console.print(f"[green]📞 Calling {number}[/green]")


def _end_call(dev_id):
    """Hang up, or dismiss the incoming call screen."""
    adb_shell(dev_id, "input keyevent KEYCODE_ENDCALL")
    console.print("[green]✅ Call ended[/green]")


def _open_sms_composer(dev_id, number):
    """Open the phone's messaging app with this number filled in.

    Pressing Send from here would mean tapping the app's button by coordinates,
    which moves between releases and would fail silently on the next update — so
    this hands over to the phone until the companion app can send properly.
    """
    digits = re.sub(r"[^\d+#*]", "", number or "")
    adb_shell(dev_id, f"am start -a android.intent.action.SENDTO -d sms:{digits}")
    console.print("[green]📱 Opened the message composer on the phone.[/green]")
    console.print("[dim]Sending without touching the phone needs the companion app; "
                  "until then the phone asks for the send tap.[/dim]")


def action_phone(args):
    """`fenox phone <resource>` — read the phone's own data over adb."""
    dev_id = resolve_phone_device(getattr(args, "device", None))
    if not dev_id:
        return
    resource = getattr(args, "resource", None) or "messages"
    if resource == "messages":
        print_messages(dev_id, args)
    elif resource == "calls":
        print_calls(dev_id, args)
    elif resource == "contacts":
        print_contacts(dev_id, args)
    elif resource == "calendar":
        print_calendar(dev_id, args)


def action_messages(dev_id):
    """Read the phone's messages from the terminal: threads, then a transcript."""
    names = phone_contacts(dev_id)
    state = {"cursor": 0}
    while True:
        threads, error = phone_threads(dev_id, names=names, limit=40)
        if error:
            _phone_refused("messages", error)
            return
        if not threads:
            console.print("[yellow]No message threads on this phone.[/yellow]")
            _wait_any_key()
            return
        by_number = {str(i + 1): t for i, t in enumerate(threads)}
        rows = [(None, "THREADS", "", 1)]
        for number, thread in by_number.items():
            unread = f"[bold yellow]{thread['unread']} unread[/bold yellow]" if thread["unread"] else f"[dim]{thread['count']} msgs[/dim]"
            rows.append((number, f"📨 {thread['label']}",
                         f"{thread['when']} · {unread} · {thread['snippet'][:44]}", 1))
        rows.append((None, "ACTIONS", "", 2))
        rows.append(("s", "Search all messages", "", 2))
        rows.append(("r", "Reload from the phone", "", 2))
        choice = run_menu(
            f"📨  MESSAGES · {dev_id}",
            rows,
            breadcrumb=f"dashboard › device › messages · {len(threads)} thread(s)",
            subtitle="read straight from the phone — nothing is uploaded",
            accent="bright_cyan",
            two_col=True,
            state=state,
        )
        if choice is None:
            return
        if choice == "r":
            names = phone_contacts(dev_id)
            continue
        if choice == "s":
            query = Prompt.ask("Search messages for")
            messages, error = phone_search_messages(dev_id, query, names=names)
            if error:
                _phone_refused("messages", error)
            elif not messages:
                console.print(f"[yellow]Nothing matches '{query}'.[/yellow]")
            else:
                render_transcript(list(reversed(messages)), names)
            _wait_any_key()
            continue
        thread = by_number.get(choice)
        if thread:
            _message_thread_screen(dev_id, thread, names)
            names = phone_contacts(dev_id)


def _message_thread_screen(dev_id, thread, names):
    """One conversation: read it, then act on it."""
    messages, error = phone_thread_messages(dev_id, thread["thread_id"], names=names)
    if error:
        _phone_refused("messages", error)
        _wait_any_key()
        return
    console.print(Panel(
        f"[bold bright_white]{thread['label']}[/bold bright_white]\n"
        f"[dim]{len(messages)} message(s) shown · {thread['count']} in total · "
        f"last {thread['when']}[/dim]",
        box=box.ROUNDED, border_style="bright_cyan", title_align="left",
        title=Text("THREAD", style="bright_cyan"), padding=(0, 1)))
    render_transcript(messages, names)
    options = [
        ("1", "Mark this thread as read"),
        ("2", "Call this number"),
        ("3", "Open it in the phone's messaging app"),
        ("4", "Export this thread to a file"),
    ]
    while True:
        choice = run_menu(f"📨  {thread['label']}", options,
                          breadcrumb="dashboard › device › messages › thread",
                          subtitle="sent messages need the phone's own app until the companion app lands",
                          accent="bright_cyan")
        if choice is None:
            return
        if choice == "1":
            ok, note = phone_mark_thread_read(dev_id, thread["thread_id"])
            console.print(f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'} {note}[/]")
        elif choice == "2":
            _call_number(dev_id, thread["address"])
        elif choice == "3":
            _open_sms_composer(dev_id, thread["address"])
        elif choice == "4":
            default = os.path.expanduser(f"~/fenox-thread-{thread['thread_id']}.txt")
            export_transcript(Prompt.ask("Write to", default=default), messages,
                              f"Thread {thread['thread_id']} · {thread['label']}")
        _wait_any_key()


def _public_thread(thread, redact=False):
    """A thread as JSON, with the personal fields redacted on request."""
    return {
        "thread_id": thread["thread_id"],
        "address": "…" if redact else thread["address"],
        "label": (f"…{re.sub(r'\\D', '', thread['address'])[-4:]}" if redact else thread["label"]),
        "when": thread["when"],
        "messages": thread["count"],
        "unread": thread["unread"],
        "snippet": _redact_body(thread["snippet"]) if redact else thread["snippet"],
    }

def _parse_when(text):
    """A human time as epoch milliseconds, or None when it cannot be read.

    Accepts `HH:MM` (today, or tomorrow once that time has passed) and
    `YYYY-MM-DD HH:MM` — the two forms a person actually types. Deliberately not
    a date library: three patterns, checked in order.
    """
    text = str(text or "").strip()
    now = datetime.datetime.now()
    for pattern, to_dt in (
            ("%H:%M", lambda base: base if base > now else base + datetime.timedelta(days=1)),
            ("%Y-%m-%d %H:%M", lambda base: base),
            ("%Y-%m-%d", lambda base: base),
    ):
        try:
            base = datetime.datetime.strptime(text, pattern)
        except ValueError:
            continue
        return int(to_dt(base).timestamp() * 1000)
    return None


def _fmt_range(event):
    """One event's span the way a person reads it."""
    try:
        begin = datetime.datetime.fromtimestamp(int(event["begin"]) / 1000)
        end = datetime.datetime.fromtimestamp(int(event["end"]) / 1000)
    except (TypeError, ValueError, OSError, KeyError):
        return event.get("when", "—")
    if event.get("all_day"):
        return f"{begin.strftime('%d %b')} (all day)"
    same_day = begin.date() == end.date()
    tail = end.strftime("%H:%M") if same_day else end.strftime("%d %b %H:%M")
    return f"{begin.strftime('%d %b %H:%M')}–{tail}"


def print_contacts(dev_id, args):
    """CLI rendering for contacts: the phone book, searchable."""
    redact = getattr(args, "redact", False)
    contacts, error = phone_contact_rows(
        dev_id, search=getattr(args, "search", None),
        limit=getattr(args, "limit", None) or 40)
    if error:
        _phone_refused("contacts", error)
        return False
    if getattr(args, "json_out", False):
        print(json.dumps({"contacts": [
            {"name": "…" if redact else c["name"],
             "number": f"…{re.sub(r'\\D', '', c['number'])[-4:]}" if redact else c["number"],
             "type": c["type"]} for c in contacts]}, indent=2))
        return True
    if not contacts:
        console.print("[yellow]No contacts match." +
                      ("" if getattr(args, "search", None) else " The phone shares none — "
                       "unlock it once after plugging in.") + "[/yellow]")
        return True
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold bright_cyan", pad_edge=False)
    table.add_column("Name", no_wrap=True, max_width=30)
    table.add_column("Number", no_wrap=True)
    table.add_column("Type", style="dim")
    for contact in contacts:
        number = (f"…{re.sub(r'\\D', '', contact['number'])[-4:]}" if redact
                  else contact["number"])
        table.add_row(contact["name"], number, contact["type"])
    console.print(table)
    console.print(f"[dim]{len(contacts)} contact(s)"
                  + (f" · matching '{args.search}'" if getattr(args, "search", None) else "")
                  + "[/dim]")
    if getattr(args, "export", None):
        target = os.path.expanduser(args.export)
        try:
            with open(target, "w", encoding="utf-8") as f:
                for contact in contacts:
                    f.write(f"{contact['name']}\t{contact['number']}\n")
            console.print(f"[green]✅ Exported {len(contacts)} contact(s) to {_pretty_path(target)}[/green]")
        except OSError as exc:
            console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
    return True


def print_calendar(dev_id, args):
    """CLI rendering for the calendar: upcoming occurrences, or adding one."""
    redact = getattr(args, "redact", False)
    title = getattr(args, "add", None)
    if title:
        begin = _parse_when(getattr(args, "at", None))
        if begin is None:
            console.print("[yellow]--add needs --at, as `HH:MM` or `YYYY-MM-DD HH:MM`.[/yellow]")
            return False
        end = begin + int(getattr(args, "duration", None) or 60) * 60_000
        ok, note = phone_add_event(dev_id, title, begin, end,
                                   calendar_id=getattr(args, "calendar", None) or 1)
        console.print(f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'} {note}[/]")
        if not ok:
            return False
    days = getattr(args, "days", None)
    days = 7 if days is None else days
    events, error = phone_events(dev_id, days=days,
                                 calendar_id=getattr(args, "calendar", None),
                                 search=getattr(args, "search", None),
                                 limit=getattr(args, "limit", None) or 30)
    if error:
        _phone_refused("calendar", error)
        return False
    if getattr(args, "json_out", False):
        print(json.dumps({"days": days, "events": [
            {"title": "…" if redact else e["title"],
             "when": e["when"], "range": _fmt_range(e),
             "where": "" if redact else e["where"]} for e in events]}, indent=2))
        return True
    if not events:
        console.print(f"[yellow]Nothing on the calendar in the next {days} day(s).[/yellow]")
        return True
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold bright_cyan", pad_edge=False)
    table.add_column("When", no_wrap=True, style="dim")
    table.add_column("Event", overflow="fold")
    table.add_column("Where", style="dim", overflow="ellipsis", no_wrap=True, max_width=24)
    for event in events:
        shown = _redact_body(event["title"]) if redact else event["title"]
        table.add_row(_fmt_range(event), shown,
                      "" if redact else event["where"])
    console.print(table)
    console.print(f"[dim]{len(events)} event(s) · next {days} days[/dim]")
    if getattr(args, "export", None):
        target = os.path.expanduser(args.export)
        try:
            with open(target, "w", encoding="utf-8") as f:
                for event in events:
                    f.write(f"[{_fmt_range(event)}] {event['title']}"
                            + (f" @ {event['where']}" if event["where"] else "") + "\n")
            console.print(f"[green]✅ Exported {len(events)} event(s) to {_pretty_path(target)}[/green]")
        except OSError as exc:
            console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
    return True


def action_calls(dev_id):
    """The phone's call log in the terminal: recent calls, then act on one."""
    names = phone_contacts(dev_id)
    state = {"cursor": 0, "missed_only": False}
    while True:
        window, error = phone_calls(dev_id, names=names, days=30)
        if error:
            _phone_refused("call log", error)
            _wait_any_key()
            return
        if not window:
            console.print("[yellow]No calls in the last 30 days on this phone.[/yellow]")
            _wait_any_key()
            return
        unread_total = _provider_count(dev_id, SMS_INBOX_URI, "read=0")
        vm_count = _provider_count(dev_id, SMS_URI, "type=4")
        calls = [c for c in window if c["kind"] == "missed"] if state["missed_only"] \
            else list(window)
        if not calls:
            console.print("[green]Nothing was missed — every call in the last 30 days "
                          "was answered or dialled out.[/green]")
            _wait_any_key()
            state["missed_only"] = False
            continue
        calls = calls[:40]
        by_number = {str(i + 1): call for i, call in enumerate(calls)}
        # One full-width line above the list: every number on this phone is on its
        # way to being either an unread message, an unlistened voicemail, a missed
        # call to return, or all squared away.
        # Compact on purpose: the line must survive an 80-column terminal unwrapped.
        # A count the phone refuses to give is a dash, not a zero: zero would read
        # as all-clear when it is really "cannot see".
        unread_part = "—" if unread_total is None else f"{unread_total} unread"
        vm_part = "—" if vm_count is None else f"{vm_count} unheard"
        missed_count = len([c for c in window if c["kind"] == "missed"])
        summary = (f"💬 {unread_part}   ·   ✉ {vm_part}   ·   "
                   f"✆ {missed_count} missed · last 30 days")
        # Grouped by day, newest first: the way the phone's own app arranges a log,
        # and easier to scan than one flat list when days blur together.
        rows = []
        current_day = None
        for number, call in by_number.items():
            day = _day_label(call["date"])
            if day != current_day:
                rows.append((None, day, "", 1))
                current_day = day
            mark, colour = CALL_MARKS.get(call["kind"], CALL_MARKS["call"])
            outcome = "[bold yellow]new[/bold yellow]" if call["new"] \
                else f"[dim]{call['kind']}[/dim]"
            rows.append((number, f"[{colour}]{mark}[/{colour}] {call['label']}",
                         f"{call['when'].split()[-1] if ' ' in call['when'] else call['when']}"
                         f" · {outcome} · {call['duration']}", 1))
        rows.append((None, "ACTIONS", "", 2))
        rows.append(("d", "Dial a number…", "", 2))
        rows.append(("m", "Show every call" if state["missed_only"] else "Show missed only",
                     "", 2))
        rows.append(("s", "Search by number or name…", "", 2))
        rows.append(("e", "Export the call log to a file", "", 2))
        rows.append(("r", "Reload from the phone", "", 2))
        missed_note = " · showing missed only" if state["missed_only"] else ""
        choice = run_menu(
            f"📞  CALL LOG · {dev_id}",
            rows,
            breadcrumb=f"dashboard › device › calls · {len(window)} call(s) in 30 days{missed_note}",
            subtitle="read from the phone itself — nothing dials or deletes without asking",
            body=Text.from_markup(f"  [bright_cyan]{summary}[/bright_cyan]"),
            accent="bright_cyan",
            two_col=True,
            state=state,
        )
        if choice is None:
            return
        if choice == "m":
            state["missed_only"] = not state["missed_only"]
            state["cursor"] = 0
            continue
        if choice == "r":
            names = phone_contacts(dev_id)
            continue
        if choice == "d":
            number = Prompt.ask("Number to call")
            if str(number).strip():
                _call_number(dev_id, number)
                _wait_any_key()
            continue
        if choice == "s":
            query = Prompt.ask("Search calls by number or name")
            found, error = phone_calls(dev_id, names=names, days=0, search=query)
            if error:
                _phone_refused("call log", error)
            elif not found:
                console.print(f"[yellow]Nothing matches '{query}'.[/yellow]")
            else:
                render_calls(found[:40])
                console.print(f"[dim]{len(found)} call(s) · {phone_call_counts(found)}[/dim]")
            _wait_any_key()
            continue
        if choice == "e":
            export_calls(Prompt.ask("Write to",
                                    default=os.path.expanduser("~/fenox-calls.txt")), calls)
            _wait_any_key()
            continue
        call = by_number.get(choice)
        if call:
            _call_detail_screen(dev_id, call, names)
            names = phone_contacts(dev_id)


def action_contacts(dev_id):
    """The phone's address book in the terminal: search, call, message."""
    state = {"cursor": 0, "query": ""}
    while True:
        contacts, error = phone_contact_rows(dev_id, search=state["query"] or None, limit=40)
        if error:
            _phone_refused("contacts", error)
            _wait_any_key()
            return
        if not contacts:
            console.print("[yellow]" + (f"No contact matches '{state['query']}'." if state["query"]
                                        else "The phone shares no contacts — unlock it once "
                                             "after plugging in.") + "[/yellow]")
            _wait_any_key()
            return
        by_number = {str(i + 1): contact for i, contact in enumerate(contacts)}
        rows = [(None, f"CONTACTS · {len(contacts)} shown", "", 1)]
        for number, contact in by_number.items():
            rows.append((number, f"👤 {contact['name']}",
                         f"{contact['number']}" + (f" · {contact['type']}" if contact["type"] else ""), 1))
        rows.append((None, "ACTIONS", "", 2))
        rows.append(("c", "Call a number…", "", 2))
        rows.append(("s", "Search contacts…", "", 2))
        rows.append(("e", "Export to a file", "", 2))
        rows.append(("r", "Reload from the phone", "", 2))
        choice = run_menu(
            "👤  CONTACTS",
            rows,
            breadcrumb=f"dashboard › device › contacts"
                       + (f" · matching '{state['query']}'" if state["query"] else ""),
            subtitle="read from the phone itself — nothing is uploaded",
            accent="bright_cyan",
            two_col=True,
            state=state,
        )
        if choice is None:
            return
        if choice == "c":
            _call_number(dev_id, Prompt.ask("Number to call"))
            _wait_any_key()
            continue
        if choice == "s":
            state["query"] = Prompt.ask("Search contacts by name or number").strip()
            state["cursor"] = 0
            continue
        if choice == "r":
            continue
        if choice == "e":
            target = os.path.expanduser(Prompt.ask(
                "Write to", default=os.path.expanduser("~/fenox-contacts.tsv")))
            try:
                with open(target, "w", encoding="utf-8") as f:
                    for contact in contacts:
                        f.write(f"{contact['name']}\t{contact['number']}\n")
                console.print(f"[green]✅ Exported {len(contacts)} contact(s) to {_pretty_path(target)}[/green]")
            except OSError as exc:
                console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
            _wait_any_key()
            continue
        contact = by_number.get(choice)
        if contact:
            _contact_detail_screen(dev_id, contact)


def _contact_detail_screen(dev_id, contact):
    """One contact: reach them, or find them elsewhere in the phone's data."""
    console.print(Panel(
        f"[bold bright_white]{contact['name']}[/bold bright_white]\n"
        f"[dim]{contact['number']}" + (f" · {contact['type']}" if contact["type"] else "") + "[/dim]",
        box=box.ROUNDED, border_style="bright_cyan", title_align="left",
        title=Text("👤 CONTACT", style="bright_cyan"), padding=(0, 1)))
    options = [
        ("1", f"Call {contact['number']}"),
        ("2", "Open it in the phone's dialler"),
        ("3", "Send a message"),
        ("4", "Every call with this number"),
        ("5", "Messages with this number"),
    ]
    while True:
        choice = run_menu(f"👤  {contact['name']}", options,
                          breadcrumb="dashboard › device › contacts › contact",
                          subtitle="nothing is dialled until you confirm it",
                          accent="bright_cyan")
        if choice is None:
            return
        if choice == "1":
            _call_number(dev_id, contact["number"])
        elif choice == "2":
            digits = re.sub(r"[^\d+#*]", "", contact["number"] or "")
            adb_shell(dev_id, f"am start -a android.intent.action.DIAL -d tel:{digits}")
            console.print("[green]📱 Opened the dialler with this number.[/green]")
        elif choice == "3":
            _open_sms_composer(dev_id, contact["number"])
        elif choice == "4":
            history, error = phone_calls(dev_id, days=0, number=contact["number"])
            if error:
                _phone_refused("call log", error)
            else:
                render_calls(history)
                console.print(f"[dim]{len(history)} call(s) · {phone_call_counts(history)}[/dim]")
        elif choice == "5":
            found, error = phone_search_messages(dev_id, re.sub(r"\D", "", contact["number"]), limit=30)
            if error:
                _phone_refused("messages", error)
            elif not found:
                console.print("[yellow]No messages with this number.[/yellow]")
            else:
                render_transcript(list(reversed(found)), phone_contacts(dev_id))
        _wait_any_key()


def action_calendar(dev_id):
    """The phone's calendar in the terminal: upcoming, searched, and addable."""
    state = {"cursor": 0, "days": 7}
    while True:
        events, error = phone_events(dev_id, days=state["days"], limit=40)
        if error:
            _phone_refused("calendar", error)
            _wait_any_key()
            return
        if not events:
            console.print(f"[yellow]Nothing on the calendar in the next {state['days']} day(s)." "[/yellow]")
            _wait_any_key()
            state["days"] = min(state["days"] * 2, 90)
            continue
        by_number = {str(i + 1): event for i, event in enumerate(events)}
        rows = [(None, f"UPCOMING · {state['days']} days", "", 1)]
        for number, event in by_number.items():
            marker = "☀" if event["all_day"] else "🕐"
            rows.append((number, f"{marker} {event['title']}", _fmt_range(event), 1))
        rows.append((None, "ACTIONS", "", 2))
        rows.append(("a", "Add an event…", "", 2))
        rows.append(("w", "Widen the window" if state["days"] < 90 else "Window is 90 days", "", 2))
        rows.append(("s", "Search events…", "", 2))
        rows.append(("e", "Export to a file", "", 2))
        rows.append(("r", "Reload from the phone", "", 2))
        choice = run_menu(
            f"📅  CALENDAR · {dev_id}",
            rows,
            breadcrumb=f"dashboard › device › calendar · next {state['days']} days",
            subtitle="recurring events appear every time they occur",
            accent="bright_cyan",
            two_col=True,
            state=state,
        )
        if choice is None:
            return
        if choice == "a":
            title = Prompt.ask("Event title").strip()
            if not title:
                continue
            at = Prompt.ask("When (HH:MM, or YYYY-MM-DD HH:MM)",
                            default=datetime.datetime.now().strftime("%H:%M"))
            begin = _parse_when(at)
            if begin is None:
                console.print("[yellow]Could not read that time — nothing added.[/yellow]")
                _wait_any_key()
                continue
            minutes = Prompt.ask("Length in minutes", default="60")
            try:
                end = begin + int(minutes) * 60_000
            except ValueError:
                end = begin + 3_600_000
            ok, note = phone_add_event(dev_id, title, begin, end)
            console.print(f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'} {note}[/]")
            _wait_any_key()
            continue
        if choice == "w":
            state["days"] = min(state["days"] * 2, 90)
            state["cursor"] = 0
            continue
        if choice == "s":
            query = Prompt.ask("Search event titles").strip()
            found, error = phone_events(dev_id, days=90, search=query or None)
            if error:
                _phone_refused("calendar", error)
            elif not found:
                console.print(f"[yellow]Nothing matches '{query}'.[/yellow]")
            else:
                for event in found[:20]:
                    console.print(f"  [dim]{_fmt_range(event)}[/dim] {event['title']}")
            _wait_any_key()
            continue
        if choice == "e":
            target = os.path.expanduser(Prompt.ask(
                "Write to", default=os.path.expanduser("~/fenox-calendar.txt")))
            try:
                with open(target, "w", encoding="utf-8") as f:
                    for event in events:
                        f.write(f"[{_fmt_range(event)}] {event['title']}"
                                + (f" @ {event['where']}" if event["where"] else "") + "\n")
                console.print(f"[green]✅ Exported {len(events)} event(s) to {_pretty_path(target)}[/green]")
            except OSError as exc:
                console.print(f"[red]❌ Could not write {target}: {exc}[/red]")
            _wait_any_key()
            continue
        if choice == "r":
            continue
        event = by_number.get(choice)
        if event:
            console.print(Panel(
                f"[bold bright_white]{event['title']}[/bold bright_white]\n"
                f"[dim]{_fmt_range(event)}" + (f" · {event['where']}" if event["where"] else "") + "[/dim]",
                box=box.ROUNDED, border_style="bright_cyan", title_align="left",
                title=Text("EVENT", style="bright_cyan"), padding=(0, 1)))
            _wait_any_key()


def _call_detail_screen(dev_id, call, names):
    """One call: what happened, then what to do about it."""
    mark, colour = CALL_MARKS.get(call["kind"], CALL_MARKS["call"])
    console.print(Panel(
        f"[bold bright_white]{call['label']}[/bold bright_white]\n"
        f"[dim]{call['kind']} · {call['when']} · length {call['duration']}"
        + (" · flagged new on the phone" if call["new"] else "") + "[/dim]",
        box=box.ROUNDED, border_style=colour, title_align="left",
        title=Text(f"{mark} CALL", style=colour), padding=(0, 1)))
    options = [
        ("1", f"Call {call['number']} back"),
        ("2", "Open it in the phone's dialler"),
        ("3", "Send a message instead"),
        ("4", "Every call with this number"),
        ("5", "Export this history to a file"),
        ("6", "Remove this call from the log"),
    ]
    while True:
        choice = run_menu(f"📞  {call['label']}", options,
                          breadcrumb="dashboard › device › calls › call",
                          subtitle="nothing is dialled or deleted until you confirm it",
                          accent="bright_cyan")
        if choice is None:
            return
        if choice == "1":
            _call_number(dev_id, call["number"])
        elif choice == "2":
            digits = re.sub(r"[^\d+#*]", "", call["number"] or "")
            adb_shell(dev_id, f"am start -a android.intent.action.DIAL -d tel:{digits}")
            console.print("[green]📱 Opened the dialler with this number.[/green]")
        elif choice == "3":
            _open_sms_composer(dev_id, call["number"])
        elif choice == "4":
            history, error = phone_calls(dev_id, names=names, days=0, number=call["number"])
            if error:
                _phone_refused("call log", error)
            else:
                render_calls(history)
                console.print(f"[dim]{len(history)} call(s) · {phone_call_counts(history)}[/dim]")
            _wait_any_key()
            continue
        elif choice == "5":
            history, error = phone_calls(dev_id, names=names, days=0, number=call["number"])
            if error:
                _phone_refused("call log", error)
            else:
                tail = re.sub(r"\D", "", call["number"])[-6:] or "history"
                export_calls(Prompt.ask(
                    "Write to", default=os.path.expanduser(f"~/fenox-calls-{tail}.txt")),
                    history)
            _wait_any_key()
            continue
        elif choice == "6":
            if not Confirm.ask(
                    f"[bold red]Remove this {call['kind']} call from the phone's log?[/bold red] "
                    "It cannot be undone.", default=False):
                console.print("[dim]Kept.[/dim]")
                _wait_any_key()
                continue
            ok, note = phone_delete_call(dev_id, call["id"])
            console.print(f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'} {note}[/]")
            if ok:
                _wait_any_key()
                return                     # it is gone; nothing to show here now
            _wait_any_key()
            continue
        _wait_any_key()


def _device_summary(key):
    """One-line status for a device, from config only (cheap, safe to redraw)."""
    info = DEVICES.get(key, {})
    bits = [str(info.get("model") or "Android device")]
    if info.get("type") == "usb":
        if info.get("serial"):
            bits.append(str(info["serial"]))
    elif info.get("ip"):
        bits.append(f"{info.get('ip')}:{info['port']}" if info.get("port")
                    else str(info.get("ip")))
    if not is_device_enabled(info):
        bits.append("disabled")
    return " · ".join(bits)

def _open_config_in_editor():
    """Open ~/.fenox.json in the user's editor, without assuming one exists."""
    editor = os.environ.get("EDITOR") or next(
        (e for e in ("nano", "vim", "vi", "emacs") if shutil.which(e)), None)
    if not editor:
        console.print(f"[yellow]No editor found — your config is at {CONFIG_PATH}[/yellow]")
        return
    try:
        subprocess.call([editor, CONFIG_PATH])
    except OSError as e:
        console.print(f"[red]❌ Could not launch {editor}: {e}[/red]")

def _rename_device_prompt():
    if not DEVICES:
        console.print("[yellow]No devices yet — run [cyan]fenox discover[/cyan] to find some.[/yellow]")
        return
    action_rename_device(Prompt.ask("Device to rename", choices=list(DEVICES.keys())))

def device_actions(key):
    """Every action for one device on a single screen, grouped by category.

    The whole toolset is visible at once and numbered continuously, so any action
    is one typed number away instead of being buried in a category sub-menu.
    """
    if key not in DEVICES:
        return
    rows, handlers, number = [], {}, 0
    for section, column, actions in _device_action_sections(key):
        rows.append((None, section, "", column))
        for label, needs_device, handler in actions:
            number += 1
            rows.append((str(number), label, "", column))
            handlers[str(number)] = (needs_device, handler)
    while True:
        choice = run_menu(
            f"📱  {key.upper()}",
            rows,
            breadcrumb="dashboard › device",
            subtitle=_device_summary(key),
            accent="bright_cyan",
            two_col=True,
        )
        if choice is None:
            return
        needs_device, handler = handlers[choice]
        dev_id = check_and_connect(key, interactive=True) if needs_device else None
        if needs_device and not dev_id:
            console.print(f"[red]❌ {key} is not reachable right now — run Doctor, or pair it again.[/red]")
        else:
            handler(dev_id)
        _wait_any_key()

# --- Per-device actions -------------------------------------------------------
# Every action is one entry: (label, needs the device online, handler). The handler
# receives a device id, or None for the configuration entries. device_actions
# numbers them in order, so the screen stays a single numbered list.

def _action_wake(dev_id):
    run_cmd(f"adb -s {dev_id} shell input keyevent KEYCODE_WAKEUP")
    console.print("[green]✅ Screen woken[/green]")

def _action_lock(dev_id):
    run_cmd(f"adb -s {dev_id} shell input keyevent KEYCODE_SLEEP")
    console.print("[green]✅ Screen locked[/green]")

def _with_registered_app(run):
    """Ask which registered app, then hand its key to `run`."""
    if not APPS:
        console.print("[yellow]No apps registered yet — add one from the dashboard first.[/yellow]")
        return
    run(Prompt.ask("App", choices=list(APPS.keys())))

def _edit_device_prompt(key):
    info = DEVICES[key]
    new_ip = Prompt.ask("IP", default=info.get("ip", ""))
    new_port = Prompt.ask("Port", default=str(info.get("port", "")))
    new_model = Prompt.ask("Model", default=info.get("model", ""))
    DEVICES[key] = {**info, "ip": new_ip, "port": new_port, "model": new_model}
    save_config()
    console.print(f"[green]✅ {key} updated[/green]")

def _toggle_device_flag(key):
    info = DEVICES[key]
    info["disabled"] = not info.get("disabled", False)
    save_config()
    console.print(f"[green]✅ {key} {'disabled' if info['disabled'] else 'enabled'}[/green]")

def _remove_device(key):
    if not Confirm.ask(f"[red]Remove '{key}' from fenox?[/red]"):
        return False
    del DEVICES[key]
    save_config()
    console.print(f"[green]✅ {key} removed[/green]")
    return True

def _refresh_device_status(key):
    dev_id = check_and_connect(key, interactive=False)
    if dev_id:
        console.print(f"[green]✅ Reachable as {dev_id}[/green]")
    else:
        console.print("[yellow]○ Not reachable right now — check the IP, port or cable.[/yellow]")

def _device_action_sections(key):
    """The per-device toolset: (section, column, [(label, needs device, handler)]).

    Column 2 holds the sections that sit beside the first three on a wide terminal.
    """
    return [
        ("PHONE", 1, [
            ("📨 Read messages", True, lambda d: action_messages(d)),
            ("📞 Read the call log", True, lambda d: action_calls(d)),
            ("👤 Read contacts", True, lambda d: action_contacts(d)),
            ("📅 Read the calendar", True, lambda d: action_calendar(d)),
        ]),
        ("SCREEN & INPUT", 1, [
            ("Mirror Screen & Control", True, lambda d: action_mirror(key)),
            ("Screenshot", True, lambda d: action_media(key, "screenshot")),
            ("Record the screen", True, lambda d: action_media(key, "record")),
            ("Wake the screen", True, _action_wake),
            ("Lock the screen", True, _action_lock),
            ("Type text", True, _action_type_text),
            ("Tap at XY", True, _action_tap_screen),
            ("Swipe gesture", True, _action_swipe),
            ("Key combos", True, _action_key_combo),
            ("Copy text from PC to device", True, _action_clipboard_copy),
            ("Read the device clipboard", True, _action_clipboard_read),
            ("Open a URL on the device", True, _action_open_url),
            ("Open the last capture", True, lambda d: _open_last_capture(key)),
        ]),
        ("APPS", 1, [
            ("Open an app on this device", True,
             lambda d: _with_registered_app(lambda ak: action_open(ak, key))),
            ("List installed apps", True, _action_list_apps),
            ("Uninstall an app", True, _action_uninstall_app),
            ("Clear an app's data", True, _action_clear_app_data),
            ("Force stop an app", True, _action_force_stop),
            ("App info", True, _action_app_info),
            ("Install an APK from the PC", True, _action_install_apk_from_pc),
            ("Nuke and relaunch an app", True,
             lambda d: _with_registered_app(lambda ak: action_nuke(ak, key))),
        ]),
        ("FILES", 1, [
            ("Push a file to the device", True, _action_push_file),
            ("Pull a file from the device", True, _action_pull_file),
            ("Browse device storage", True, _action_browse_storage),
        ]),
        ("DEVICE CONTROL", 2, [
            ("Reboot options", True, _action_reboot_menu),
            ("Toggle Wi-Fi", True, _action_toggle_wifi),
            ("Toggle mobile data", True, _action_toggle_data),
            ("Toggle Bluetooth", True, _action_toggle_bluetooth),
            ("Volume", True, _action_volume_control),
            ("Brightness", True, _action_brightness_control),
            ("Interactive shell", True, _action_interactive_shell),
        ]),
        ("DEV TOOLS", 2, [
            ("Device info", True, _action_device_info_dashboard),
            ("Battery", True, _action_battery_info),
            ("Network", True, _action_network_info),
            ("Storage", True, _action_storage_info),
            ("Running processes", True, _action_running_processes),
            ("Send a notification", True, _action_send_notification),
            ("Read notifications", True, _action_read_notifications),
            ("Bind app ports", True,
             lambda d: _with_registered_app(lambda ak: action_bind(ak, key))),
            ("Follow app logs", True,
             lambda d: _with_registered_app(lambda ak: action_logs(ak, key))),
            ("Live health monitor", True, _action_health_monitor),
        ]),
        ("CONFIGURE DEVICE", 2, [
            ("Edit name / address / model", False, lambda d: _edit_device_prompt(key)),
            ("Enable or disable", False, lambda d: _toggle_device_flag(key)),
            ("Check if it is reachable now", False, lambda d: _refresh_device_status(key)),
            ("Remove this device", False, lambda d: _remove_device(key)),
        ]),
    ]

def app_actions(key):
    data = APPS[key]
    pkg = data.get("package") or resolve_package(key) or "?"
    options = [
        ("1", "Run local (pick device)"), ("2", "Run remote (pick device)"),
        ("3", "Run on ALL online devices"), ("4", "Open app on a device"),
        ("5", "Build release APK"), ("6", "flutter clean + pub get"),
        ("7", "Start backend"),
    ]
    subtitle = f"{_pretty_path(os.path.expanduser(str(data.get('path', ''))))} · port {data.get('port', '')} · {pkg}"
    while True:
        choice = run_menu(f"📦  {key.upper()}", options,
                          breadcrumb="dashboard › app",
                          subtitle=subtitle, accent="bright_green")
        if choice is None: return
        if choice in ("1", "2"):
            dev_key = Prompt.ask("Device", choices=list(DEVICES.keys()) + ["all"], default=list(DEVICES.keys())[0] if DEVICES else "all")
            action_run(key, dev_key, is_remote=(choice == "2"))
        elif choice == "3":
            action_run(key, "all", is_remote=False)
        elif choice == "4":
            dev_key = Prompt.ask("Device", choices=list(DEVICES.keys()), default=list(DEVICES.keys())[0] if DEVICES else "all")
            action_open(key, dev_key)
        elif choice == "5":
            action_build(key)
        elif choice == "6":
            path = os.path.expanduser(APPS[key].get("path", ""))
            if not os.path.isdir(path):
                console.print(f"[red]❌ Project path not found: {path}[/red]")
            else:
                os.chdir(path)
                console.print("[yellow]🧹 flutter clean...[/yellow]"); os.system("flutter clean")
                console.print("[yellow]📦 flutter pub get...[/yellow]"); os.system("flutter pub get")
        elif choice == "7":
            action_backend(key)
        _wait_any_key()

def action_discover():
    console.print(Panel.fit("[bold cyan]📡 DEVICE DISCOVERY[/bold cyan]", border_style="cyan"))
    found = {}
    # 1. mDNS discovery
    for line in run_cmd("adb mdns services 2>/dev/null").splitlines():
        if "_adb-tls-connect" in line:
            parts = line.split()
            if len(parts) >= 3:
                addr = parts[2]
                if ":" in addr:
                    ip, port = addr.rsplit(":", 1)
                    found.setdefault(ip, {"ports": []})["ports"].append(port)
    # 2. optional nmap subnet scan
    if shutil.which("nmap"):
        known = [info.get("ip") for info in DEVICES.values() if info.get("ip")]
        if known:
            base = ".".join(known[0].split(".")[:3])
            if Confirm.ask(f"[cyan]Also scan {base}.0/24 with nmap for wireless-debugging ports? (~30s)[/cyan]", default=False):
                console.print("[yellow]Scanning...[/yellow]")
                out = run_cmd(f"timeout 90 nmap -p 37000-44000 {base}.0/24 --open -T4 --host-timeout 10s 2>/dev/null")
                cur = None
                for line in out.splitlines():
                    m = re.match(r"Nmap scan report for [\w.-]+ \((\d+\.\d+\.\d+\.\d+)\)", line)
                    if m:
                        cur = m.group(1)
                        found.setdefault(cur, {"ports": []})
                    elif cur and "/tcp" in line and "open" in line:
                        port = line.split("/")[0].strip()
                        if port.isdigit():
                            found[cur]["ports"].append(port)
    if not found:
        console.print("[yellow]⚠️ No new devices discovered.[/yellow]")
        return
    console.print(f"\n[green]📡 Discovered {len(found)} device(s):[/green]")
    for ip, info in found.items():
        known = any(d.get("ip") == ip for d in DEVICES.values())
        tag = "[dim]known[/dim]" if known else "[green]new[/green]"
        console.print(f"  {ip} {tag} ports: {', '.join(sorted(set(info['ports'])))}")
    added = 0
    for ip, info in found.items():
        if any(d.get("ip") == ip for d in DEVICES.values()):
            continue
        model = ""
        port = ""
        for p in sorted(set(info["ports"])):
            connected, _ = try_connect(ip, p)
            if connected:
                port = p
                model = run_cmd(f"timeout 4 adb -s {ip}:{p} shell getprop ro.product.model").strip()
                break
        if Confirm.ask(f"[cyan]Add {ip} ({model or 'unknown model'}) to config?[/cyan]", default=True):
            name = Prompt.ask("Name", default=(model or "phone").replace(" ", "").lower() or "newphone")
            DEVICES[name] = {"ip": ip, "model": model, "port": port}
            save_config()
            console.print(f"[green]✅ Device '{name}' added![/green]")
            added += 1
    if added:
        console.print(f"[green]✨ {added} device(s) added.[/green]")

# --- App & Device Management Wizards (zero-friction) ---
def _sanitize_name(raw):
    name = re.sub(r"[^a-z0-9_]", "_", str(raw or "").strip().lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name

def _repo_root(path):
    cur = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent

def _find_backend_dir(app_name, project_path):
    """Locate the backend for an app: sibling <name>_backend or common subdirs of the repo."""
    proj = os.path.abspath(os.path.expanduser(project_path))
    repo = _repo_root(proj) or proj
    base = os.path.dirname(repo)
    candidates = []
    for rel in (f"{app_name}_backend", f"{app_name}-backend", f"{app_name}_server", f"{app_name}-server", f"{app_name}_api", f"{app_name}-api"):
        candidates.append(os.path.join(base, rel))
    for rel in ("backend", "server", "api", "apps/server", "apps/api", "apps/backend", "services/api", "services/server", "server/src"):
        candidates.append(os.path.join(repo, rel))
    seen = set()
    for c in candidates:
        c = os.path.abspath(os.path.expanduser(c))
        if c in seen:
            continue
        seen.add(c)
        if os.path.isdir(c) and any(os.path.exists(os.path.join(c, f)) for f in ("package.json", "requirements.txt", "manage.py", "app.py", "server.py", "pyproject.toml", "go.mod", "Cargo.toml")):
            return c
    return None

def _detect_port(backend_path):
    """Best-effort: sniff the port a backend listens on (env file -> npm scripts -> python)."""
    if not backend_path:
        return None
    path = os.path.expanduser(backend_path)
    if not os.path.isdir(path):
        return None
    for env_file in (".env", ".env.local", ".env.development", ".env.production"):
        p = os.path.join(path, env_file)
        if os.path.exists(p):
            try:
                for line in open(p, encoding="utf-8", errors="ignore"):
                    line = line.strip()
                    m = re.match(r'^\s*PORT\s*[=:]\s*["\']?(\d{2,5})', line, re.I)
                    if m:
                        return m.group(1)
            except OSError:
                pass
    pkg = os.path.join(path, "package.json")
    if os.path.exists(pkg):
        try:
            scripts = json.load(open(pkg, encoding="utf-8", errors="ignore")).get("scripts", {})
        except Exception:
            scripts = {}
        for key in ("dev", "start", "serve"):
            script = scripts.get(key, "")
            m = re.search(r'(?:--port|-p)\s+("\d{2,5}"|\d{2,5})', script)
            if not m:
                m = re.search(r'PORT\s*=\s*("\d{2,5}"|\d{2,5})', script)
            if not m:
                m = re.search(r'--port\s+(\d{2,5})', script)
            if m:
                return m.group(1).strip('"')
    for fname in ("app.py", "server.py", "main.py", "manage.py"):
        p = os.path.join(path, fname)
        if os.path.exists(p):
            try:
                content = open(p, encoding="utf-8", errors="ignore").read()
                m = re.search(r'(?:port|PORT)\s*[=:]\s*["\']?(\d{2,5})', content)
                if m:
                    return m.group(1)
            except OSError:
                pass
    return None

def _guess_backend_cmd(backend_path):
    """Guess how to start a backend: npm scripts -> python -> go."""
    if not backend_path:
        return None
    path = os.path.expanduser(backend_path)
    pkg = os.path.join(path, "package.json")
    if os.path.exists(pkg):
        try:
            scripts = json.load(open(pkg, encoding="utf-8", errors="ignore")).get("scripts", {})
        except Exception:
            scripts = {}
        if scripts.get("dev"):
            return "npm run dev"
        if scripts.get("start"):
            return "npm start"
        if scripts.get("serve"):
            return "npm run serve"
    for f in ("manage.py", "app.py", "server.py", "main.py"):
        if os.path.exists(os.path.join(path, f)):
            return f"python {f}"
    if os.path.exists(os.path.join(path, "go.mod")):
        return "go run ."
    if os.path.exists(os.path.join(path, "Cargo.toml")):
        return "cargo run"
    return None

def _guess_remote(app_name):
    """https://<app>.<remote_domain>/api, or empty when no domain has been configured."""
    domain = str(config.get("settings", {}).get("remote_domain") or "").strip()
    if not domain or domain == "example.com":   # placeholder from older configs
        return ""
    return f"https://{app_name}.{domain}/api"

def _remote_api(app_data):
    """Remote API URL for a launch; falls back to the local URL, loudly, when unset."""
    remote = str(app_data.get("api_remote") or "").strip()
    if remote:
        return remote
    console.print("[yellow]⚠️  No remote API URL configured for this app — using the local one.[/yellow]")
    console.print("[dim]Set settings.remote_domain with [cyan]fenox init[/cyan], or re-register: "
                  "[cyan]fenox add-app --api-remote https://api.example.com --update --yes[/cyan][/dim]")
    return app_data.get("api_local", "")

def _locate_project(app_name):
    """Find a Flutter project in your projects directory whose repo/dir name matches the alias."""
    base = get_projects_dir()
    target = re.sub(r"[^a-z0-9]", "", app_name.lower())
    if not target or not os.path.isdir(base):
        return None
    generic = re.compile(r"^(mobile|app|client|frontend|apps|ui|flutter)([-_]?(app|mobile|client|frontend|ui))?$")
    matches = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "node_modules", "windows", "linux", "macos", "web", "example")]
        depth = root[len(base):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        if "pubspec.yaml" not in files or not os.path.isdir(os.path.join(root, "android")):
            continue
        repo = _repo_root(root)
        rname = re.sub(r"[^a-z0-9]", "", os.path.basename(repo).lower()) if repo else ""
        dname = re.sub(r"[^a-z0-9]", "", os.path.basename(root).lower())
        if target in (rname, dname) or (rname and target in rname) or (dname and target in dname):
            matches.append({
                "path": root,
                "exact_dir": dname == target,
                "at_root": bool(repo) and os.path.realpath(repo) == os.path.realpath(root),
                "generic": bool(generic.match(os.path.basename(root).lower())),
            })
    if not matches:
        return None
    # Prefer: exact dir name match > project at the repo root > generic client dir (mobile/app/...) > first found
    matches.sort(key=lambda m: (not m["exact_dir"], not m["at_root"], not m["generic"], m["path"]))
    return matches[0]["path"]

def _name_for_project(path):
    """Pick a good alias: repo name for generic nested dirs (mobile/app/...), else the dir name."""
    repo = _repo_root(path)
    base_dir = os.path.basename(path)
    generic = re.match(r"^(mobile|app|client|frontend|apps|ui|flutter)([-_]?(app|mobile|client|frontend|ui))?$", base_dir.lower())
    if repo and os.path.realpath(repo) != os.path.realpath(path) and generic:
        name = _sanitize_name(os.path.basename(repo))
    else:
        name = _sanitize_name(base_dir)
    if not name or name in APPS:
        # Already registered (or a name collision) — never create a duplicate alias
        return None
    return name

def _build_entry(name, path, port=None, api_local=None, api_remote=None, socket_local=None, socket_remote=None, additional_ports=None, backend_path=None, backend_cmd=None):
    """Assemble an app entry, auto-guessing whatever isn't provided."""
    backend_dir = backend_path
    if not backend_dir:
        backend_dir = _find_backend_dir(name, path)
    if backend_dir:
        backend_dir = os.path.abspath(os.path.expanduser(backend_dir))
    if not port:
        port = _detect_port(backend_dir)
    if not port:
        port = "8080"
    port = str(port)
    if not api_local:
        api_local = f"http://localhost:{port}/api"
    if not api_remote:
        api_remote = _guess_remote(name)
    entry = {"path": path, "port": port, "api_local": api_local}
    if api_remote:
        entry["api_remote"] = api_remote
    if socket_local:
        entry["socket_local"] = socket_local
    if socket_remote:
        entry["socket_remote"] = socket_remote
    if additional_ports:
        entry["additional_ports"] = [p.strip() for p in str(additional_ports).split(",") if p.strip()]
    if backend_dir and os.path.isdir(backend_dir):
        cmd = backend_cmd or _guess_backend_cmd(backend_dir)
        if cmd:
            entry["backend"] = {"path": backend_dir, "cmd": cmd}
    return entry

def _print_app_summary(name, entry, updated=False):
    console.print(f"[green]✅ {'Updated' if updated else 'Added'} app '{name}'.[/green]")
    console.print(f"   path:      {entry['path']}")
    console.print(f"   port:      {entry['port']}")
    console.print(f"   api_local: {entry.get('api_local', '—')}")
    console.print(f"   api_remote:{entry.get('api_remote', '—')}")
    console.print(f"   backend:   {entry.get('backend', {}).get('cmd', '—')}  ({entry.get('backend', {}).get('path', '')})")
    console.print(f"[dim]Aliases are live now — try `{name}-all`, `{name}-release`, or `fenox run {name} <device>`.[/dim]")

def action_add_app(args=None):
    """Scriptable registration. With --name: zero prompts (or --yes). Without: guided wizard."""
    if args is None:
        args = argparse.Namespace(name=None, path=None, port=None, api_local=None, api_remote=None,
                                  socket_local=None, socket_remote=None, additional_ports=None,
                                  backend_path=None, backend_cmd=None, update=False, yes=False)
    if not args.name:
        _add_app_wizard()
        return
    name = _sanitize_name(args.name)
    if not name:
        console.print("[red]❌ Invalid app name.[/red]")
        return
    existing = name in APPS
    if existing and not args.update:
        console.print(f"[red]❌ App '{name}' already exists (use --update to modify it).[/red]")
        return
    path = args.path
    if not path:
        path = _locate_project(name)
    if not path:
        path = f"~/Projects/{name}"
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        console.print(f"[red]❌ Project path not found: {path}[/red]")
        console.print("[yellow]  Pass --path explicitly, or make sure the project lives under ~/Projects.[/yellow]")
        return
    entry = _build_entry(name, path, port=args.port, api_local=args.api_local, api_remote=args.api_remote,
                         socket_local=args.socket_local, socket_remote=args.socket_remote,
                         additional_ports=args.additional_ports, backend_path=args.backend_path,
                         backend_cmd=args.backend_cmd)
    if existing:
        old = APPS[name]
        merged = dict(old)
        merged.update({k: v for k, v in entry.items() if v})
        # Path changed → any cached package name is stale; re-resolve it
        if os.path.realpath(str(old.get("path", ""))) != os.path.realpath(entry["path"]):
            merged.pop("package", None)
        entry = merged
    APPS[name] = entry
    if not entry.get("package"):
        pkg = resolve_package(name)
        if pkg:
            entry["package"] = pkg
    save_config()
    _print_app_summary(name, entry, updated=existing)

def _add_app_wizard():
    console.print(Panel.fit("[bold green]➕ ADD NEW APP[/bold green]", border_style="green"))
    name = _sanitize_name(Prompt.ask("App name (alias)", default="newapp"))
    if name in APPS:
        console.print(f"[red]❌ App '{name}' already exists.[/red]"); return
    path_default = _locate_project(name) or os.path.join(get_projects_dir(), name)
    path = Prompt.ask("Project path", default=path_default)
    backend_dir = _find_backend_dir(name, path)
    detected = _detect_port(backend_dir) if backend_dir else None
    port = Prompt.ask("Backend port", default=detected or "8080")
    api_local = Prompt.ask("Local API URL", default=f"http://localhost:{port}/api")
    api_remote = Prompt.ask("Remote API URL", default=_guess_remote(name))
    entry = {"path": path, "port": port, "api_local": api_local}
    if api_remote.strip():
        entry["api_remote"] = api_remote.strip()
    if Confirm.ask("Does the app use websockets?", default=False):
        entry["socket_local"] = Prompt.ask("Local socket URL", default=f"http://localhost:{port}")
        entry["socket_remote"] = Prompt.ask("Remote socket URL", default="")
    extra = Prompt.ask("Additional ports (comma-separated, optional)", default="")
    if extra.strip():
        entry["additional_ports"] = [p.strip() for p in extra.split(",") if p.strip()]
    if Confirm.ask("Configure a backend launcher for this app?", default=bool(backend_dir)):
        entry["backend"] = {
            "path": Prompt.ask("Backend path", default=backend_dir or f"~/Projects/{name}_backend"),
            "cmd": Prompt.ask("Backend start command", default=_guess_backend_cmd(backend_dir) or "npm run dev"),
        }
    APPS[name] = entry
    if not entry.get("package"):
        pkg = resolve_package(name)
        if pkg:
            entry["package"] = pkg
    save_config()
    _print_app_summary(name, entry)

def action_scan(args=None):
    """Zero-friction: register every new Flutter project under your projects directory. No prompts."""
    dry_run = bool(getattr(args, "dry_run", False))
    base = get_projects_dir()
    console.print(Panel.fit(f"[bold green]🔎 REGISTER FLUTTER APPS FROM {base}[/bold green]", border_style="green"))
    if not os.path.isdir(base):
        console.print(f"[red]❌ {base} not found.[/red]"); return
    candidates = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "node_modules", "windows", "linux", "macos", "web", "example")]
        depth = root[len(base):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        if "pubspec.yaml" in files and os.path.isdir(os.path.join(root, "android")):
            candidates.append(root)
    known = {os.path.realpath(os.path.expanduser(a.get("path", ""))).rstrip("/") for a in APPS.values()}
    fresh = [c for c in candidates if os.path.realpath(c).rstrip("/") not in known]
    if not fresh:
        console.print("[green]✅ No new Flutter projects found — everything is already registered.[/green]")
        return
    table = Table(title="New Projects", show_header=True)
    for col in ["App", "Path", "Port", "Remote API", "Backend"]:
        table.add_column(col)
    added = []
    for p in sorted(fresh):
        name = _name_for_project(p)
        if not name:
            continue
        entry = _build_entry(name, p)
        if not dry_run:
            APPS[name] = entry
        added.append((name, entry))
        table.add_row(name, p, entry["port"], entry.get("api_remote", "—"), entry.get("backend", {}).get("cmd", "—"))
    console.print(table)
    if dry_run:
        console.print(f"\n[yellow]Dry run — {len(added)} project(s) found, nothing written. Re-run without --dry-run to register.[/yellow]")
        return
    if added:
        save_config()
        first = added[0][0]
        console.print(f"\n[green]✅ Registered {len(added)} project(s). Aliases are live now — try `{first}-all` or `fenox run {first} <device>`.[/green]")


def action_backend(app_key):
    if app_key not in APPS:
        console.print("[red]❌ Invalid app.[/red]"); return
    app_data = APPS[app_key]
    backend = app_data.get("backend")
    if not backend:
        console.print(f"[yellow]No backend configured for {app_key}.[/yellow]")
        if not Confirm.ask("[cyan]Configure one now?[/cyan]", default=True):
            return
        backend = {
            "path": Prompt.ask("Backend path", default=f"~/Projects/{app_key}_backend"),
            "cmd": Prompt.ask("Backend start command", default="npm run dev"),
        }
        app_data["backend"] = backend
        save_config()
    if not shutil.which("tmux"):
        console.print("[red]❌ 'tmux' is not installed.[/red]"); return
    path = os.path.expanduser(backend["path"])
    if not os.path.isdir(path):
        console.print(f"[red]❌ Backend path not found: {path}[/red]"); return
    session = f"fenox_bk_{app_key}"
    run_cmd(f"tmux kill-session -t {session} 2>/dev/null")
    os.system(f"tmux new-session -d -s {session} 'cd \"{path}\" && {backend['cmd']}'")
    console.print(f"[green]🚀 Backend for {app_key.upper()} starting in tmux session '{session}'...[/green]")
    if Confirm.ask("[cyan]Attach to backend logs?[/cyan]", default=True):
        os.system(f"tmux attach-session -t {session}")

def action_hot(app_key, full=False):
    session = f"fenox_{app_key}"
    has = run_cmd(f"tmux has-session -t {session} 2>/dev/null && echo yes")
    if not has:
        console.print(f"[yellow]No running session '{session}'. Start it first with `fenox run {app_key} <device>` (or {app_key}-all).[/yellow]")
        return
    key = "R" if full else "r"
    run_cmd(f"tmux send-keys -t {session} {key}")
    console.print(f"[green]⚡ Sent '{key}' (hot {'restart' if full else 'reload'}) to {app_key.upper()} session.[/green]")

def action_install(app_key):
    if app_key not in APPS:
        console.print("[red]❌ Invalid app.[/red]"); return
    app_data = APPS[app_key]
    apk = os.path.join(os.path.expanduser(app_data["path"]), "build", "app", "outputs", "flutter-apk", "app-release.apk")
    if not os.path.exists(apk):
        ensure_output_dirs()
        matches = sorted(Path(APKS_DIR).glob(f"{app_key}_release_*.apk"), key=os.path.getmtime, reverse=True)
        if matches:
            apk = str(matches[0])
    if not os.path.exists(apk):
        console.print(f"[yellow]No release APK found for {app_key}. Build it first (`fenox build {app_key}`).[/yellow]")
        if Confirm.ask("[cyan]Build it now?[/cyan]", default=True):
            action_build(app_key)
        return
    devs = get_connected_device_ids()
    if not devs:
        console.print("[red]❌ No devices connected.[/red]"); return
    console.print(f"[green]📦 Installing {os.path.basename(apk)} on {len(devs)} device(s)...[/green]")
    for d_id in devs:
        res = run_cmd(f"adb -s {d_id} install -r \"{apk}\"")
        ok = "Success" in res
        console.print(f"  {'✅' if ok else '❌'} {d_id}: {'installed' if ok else res.strip()[:120]}")

def action_open(app_key, dev_key):
    if app_key not in APPS:
        console.print("[red]❌ Invalid app.[/red]"); return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    package = resolve_package(app_key)
    if not package:
        package = Prompt.ask(f"[cyan]Enter Android Package Name for {app_key.upper()}[/cyan] (e.g. com.company.app)")
        APPS[app_key]["package"] = package
        save_config()
    res = run_cmd(f"adb -s {dev_id} shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
    if "Events injected" in res:
        console.print(f"[green]🚀 Launched {app_key.upper()} on {dev_key.upper()}![/green]")
    else:
        console.print(f"[yellow]⚠️ Launch output: {res.strip()[:150]}[/yellow]")

def _preflight(app_key, dev_key, is_remote):
    app_data = APPS[app_key]
    issues = []
    if not shutil.which("flutter"):
        issues.append("flutter CLI not found in PATH")
    path = os.path.expanduser(app_data["path"])
    if not os.path.isdir(path):
        issues.append(f"project path not found: {path}")
    if not is_remote and app_data.get("api_local") and shutil.which("curl"):
        code = run_cmd(f"timeout 4 curl -s -o /dev/null -w '%{{http_code}}' {app_data['api_local']}")
        if code and code != "000":
            console.print(f"[green]✅ Backend reachable ({app_data['api_local']} -> HTTP {code})[/green]")
        else:
            console.print(f"[yellow]⚠️ Backend not reachable at {app_data['api_local']}[/yellow]")
            if app_data.get("backend") and Confirm.ask("[cyan]Start the backend in tmux?[/cyan]", default=True):
                action_backend(app_key)
    for issue in issues:
        console.print(f"[red]❌ {issue}[/red]")
    if issues and not Confirm.ask("[cyan]Continue anyway?[/cyan]", default=False):
        return False
    return True

SESSION_START = time.time()

# Whether the opening screen has been drawn, and whether the sign-off has been
# printed, so the session bookends appear exactly once however we exit.
_SESSION_OPENED = False
_FAREWELL_SHOWN = False

def _human_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"

def _plural(count, singular, plural=None):
    """'1 device', '2 devices' — screens should not read like log lines."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"

def _pretty_path(path):
    """Show the home directory as ~ so the screens stay short and readable."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path

def _platform_label():
    """Human name for the platform fenox is running on."""
    if IS_WSL:
        distro = os.environ.get("WSL_DISTRO_NAME", "")
        return f"WSL {distro}".strip()
    if IS_LINUX: return "Linux"
    if IS_MACOS: return "macOS"
    return sys.platform

def _shell_integration():
    """(rcfile, installed, total) for the alias + completion lines in the rc file."""
    shell = os.path.basename(os.environ.get("SHELL", "bash"))
    comp_shell = "zsh" if "zsh" in shell else "bash"
    rcfile = "~/.zshrc" if comp_shell == "zsh" else "~/.bashrc"
    lines = ('eval "$(fenox --generate-aliases)"',
             f'eval "$(fenox --generate-completions {comp_shell})"')
    try:
        content = open(os.path.expanduser(rcfile), encoding="utf-8", errors="ignore").read()
    except OSError:
        content = ""
    return rcfile, sum(1 for line in lines if line in content), len(lines)

def _adb_probe():
    """(ok, detail) for the adb server fenox will talk to. Read-only."""
    try:
        out = subprocess.run([ADB_EXE, "-P", str(ADB_SERVER_PORT), "devices"],
                             capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL)
    except Exception as exc:
        return False, f"unreachable ({type(exc).__name__})"
    if out.returncode != 0 or "List of devices" not in out.stdout:
        return False, "not responding"
    found = [line for line in out.stdout.splitlines()[1:] if line.strip()]
    return True, f"{len(found)} device(s) visible" if found else "no devices attached yet"

def _boot_adb_server():
    """Bring up the shared adb server, showing progress instead of freezing."""
    if sys.stdin.isatty():
        with console.status(f"[dim]connecting to adb on port {ADB_SERVER_PORT}…[/dim]", spinner="dots12"):
            ensure_shared_adb_server()
            return _adb_probe()
    ensure_shared_adb_server()
    return _adb_probe()

def _session_checks(adb_ok, adb_detail):
    """Opening-screen rows: (state, label, detail) with state in ok/warn/bad."""
    checks = []
    if os.path.exists(CONFIG_PATH):
        checks.append(("ok", "config", _pretty_path(CONFIG_PATH)))
    else:
        checks.append(("warn", "config", "not created yet — defaults in use"))
    checks.append(("ok" if adb_ok else "bad", "adb server",
                   f"port {ADB_SERVER_PORT} · {adb_detail}"))
    projects = get_projects_dir()
    if os.path.isdir(projects):
        checks.append(("ok", "projects", _pretty_path(projects)))
    else:
        checks.append(("warn", "projects", f"{_pretty_path(projects)} not found — run fenox init"))
    rcfile, have, want = _shell_integration()
    if have == want:
        checks.append(("ok", "shell", f"aliases + completions in {rcfile}"))
    elif have:
        checks.append(("warn", "shell", f"{have}/{want} lines in {rcfile} — run fenox init"))
    else:
        checks.append(("warn", "shell", f"not hooked into {rcfile} — run fenox init"))
    return checks

def _boot_tip():
    """One tip per day, chosen from the ones that actually apply to this machine.

    Rotating daily keeps the opening screen from being the same sentence forever,
    and every tip is only offered when it is relevant — no telling someone with
    four devices to press `f` to find their first one. The generic key-map tip is
    a fallback, so a useful suggestion is never crowded out by it.
    """
    tips = []
    if not DEVICES:
        tips.append("press [bold]f[/bold] to find phones already on your Wi-Fi, or [bold]d[/bold] for a full health check")
    if DEVICES and not APPS:
        tips.append("press [bold]a[/bold] to register a Flutter project, or [bold]n[/bold] to scan your projects directory")
    disabled = [k for k, info in DEVICES.items() if not is_device_enabled(info)]
    if disabled:
        tips.append(f"[bold]g[/bold] toggles a device — {_plural(len(disabled), 'device')} disabled and skipped by connect and bind")
    if DEVICES and APPS:
        tips.append("open a device with its number — Screen, Apps, Files, Control, Dev tools and Config are all in there")
    if len(DEVICES) > 1:
        tips.append("press [bold]r[/bold] to screenshot every device at once, or [bold]b[/bold] to re-bind every app port")
    if not tips:                # nothing to suggest: fall back to the key map
        return "[bold]b[/bold] goes back, [bold]Esc[/bold] leaves a menu, [bold]x[/bold] quits fenox"
    # A day-based index keeps the choice stable for a whole session and changes
    # with the calendar rather than at random.
    return tips[datetime.date.today().timetuple().tm_yday % len(tips)]

def _first_run_panel():
    """Guidance shown while nothing is configured on this machine."""
    return Panel(
        "[bold bright_white]Welcome to Fenox[/bold bright_white]\n\n"
        "[dim]Nothing is configured on this machine yet.[/dim]\n\n"
        "   [bold bright_cyan]1[/bold bright_cyan]  Run [cyan]fenox init[/cyan] to choose your projects directory\n"
        "   [bold bright_cyan]2[/bold bright_cyan]  Plug in a phone with USB debugging on, then press "
        "[cyan]d[/cyan] (Doctor)\n"
        "   [bold bright_cyan]3[/bold bright_cyan]  Or press [cyan]f[/cyan] to find devices already on your Wi-Fi\n\n"
        "[dim]This notice disappears once you have a device or an app.[/dim]",
        title="[bold bright_blue]👋 First run[/bold bright_blue]",
        box=box.HEAVY, border_style="bright_blue", padding=(1, 3))

def _session_start():
    """Opening screen: brand banner, environment checks, then the adb warm-up.

    Printed once per interactive session. Without a terminal it still reports the
    same facts, just without the spinner or the key wait.
    """
    global _SESSION_OPENED
    _SESSION_OPENED = True
    console.print()
    console.print(Rule(Text.from_markup(
        f"  [bold bright_blue]⚡ fenox[/bold bright_blue] "
        f"[dim]v{FENOX_VERSION} · {_platform_label()} · Python {sys.version.split()[0]}[/dim]"),
        style="blue", align="left"))
    console.print()
    console.print(_banner())
    console.print()
    adb_ok, adb_detail = _boot_adb_server()
    rows = Table.grid(padding=(0, 2))
    rows.add_column(justify="center", width=2)
    rows.add_column(style="bold bright_white", min_width=10)
    rows.add_column(style="dim")
    marks = {"ok": "[green]✓[/green]", "warn": "[yellow]○[/yellow]", "bad": "[red]✗[/red]"}
    for state, label, detail in _session_checks(adb_ok, adb_detail):
        rows.add_row(marks[state], label, detail)
    console.print(Panel(rows, title="[bold bright_cyan]Session[/bold bright_cyan]",
                        box=box.HEAVY, border_style="bright_cyan", padding=(1, 2)))
    if not DEVICES and not APPS:
        # Nothing to choose from yet: show the guidance and go straight into the
        # dashboard. There is no "press a key to continue" pause here — the panel
        # is the dashboard's empty state, and a pause would swallow the user's
        # first choice (only Enter/Esc would have got them past it).
        console.print()
        console.print(_first_run_panel())
        return
    console.print()
    console.print(Text.from_markup(f"  [dim]💡[/dim] [dim]{_boot_tip()}[/dim]"))
    console.print(Text.from_markup(
        "  [dim]Pick a device or app by number, or run a shortcut. "
        "[bold bright_white]b[/bold bright_white]/[bold bright_white]Esc[/bold bright_white] go back, "
        "[bold bright_white]x[/bold bright_white] quits.[/dim]"))
    console.print()

def _session_events():
    """Deploys recorded during this session, newest first."""
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    events = []
    for entry in history.values():
        try:
            ts = datetime.datetime.fromisoformat(str(entry.get("ts", "")))
        except ValueError:
            continue
        if ts.timestamp() >= SESSION_START:
            events.append((ts, entry))
    return sorted(events, key=lambda pair: pair[0], reverse=True)

def _farewell(reason="quit"):
    """Sign-off for the interactive session: what happened, and what to do next."""
    headline = ("[bold bright_yellow]Session interrupted[/bold bright_yellow]"
                if reason == "interrupt"
                else "[bold bright_white]Session ended[/bold bright_white]")
    note = {"quit": "",
            "interrupt": "[dim]Ctrl+C — nothing was left running.[/dim]\n",
            "eof": "[dim]Input ended.[/dim]\n"}.get(reason, "")

    events = _session_events()
    if events:
        ts, entry = events[0]
        outcome = "[green]ok[/green]" if entry.get("ok") else "[red]failed[/red]"
        ago = _human_duration(time.time() - ts.timestamp())
        activity = (f"[dim]{_plural(len(events), 'action')} this session · last:[/dim] "
                    f"[bold bright_white]{entry.get('app', '?')}[/bold bright_white] "
                    f"[dim]→ {entry.get('device', 'all')} "
                    f"({entry.get('action', 'run')}, {outcome}, {ago} ago)[/dim]")
    else:
        activity = "[dim]No deploys this session.[/dim]"

    disabled = sum(1 for info in DEVICES.values() if not is_device_enabled(info))
    if not DEVICES and not APPS:
        hint = "Nothing is configured yet — run [bold]fenox init[/bold] to get set up."
    elif not DEVICES:
        hint = "No devices saved yet — press [bold]d[/bold] (doctor) or run [bold]fenox discover[/bold]."
    elif disabled:
        hint = f"{disabled} device(s) disabled — re-enable them from the dashboard with [bold]g[/bold]."
    else:
        hint = "Run [bold]fenox doctor[/bold] for a health check, or re-bind ports with [bold]fenox connect[/bold]."

    console.print()
    console.print(Panel(
        f"{headline}   [dim]{_human_duration(time.time() - SESSION_START)} · "
        f"{_plural(len(DEVICES), 'device')} · {_plural(len(APPS), 'app')}[/dim]\n\n"
        f"{note}{activity}\n\n"
        f"[dim]Next:[/dim] {hint}\n"
        "[dim]Come back any time with[/dim] [bold]fenox[/bold][dim] — your aliases live in the shell.[/dim]",
        title="[bold bright_blue]⚡ Fenox[/bold bright_blue]",
        box=box.HEAVY, border_style="bright_blue", padding=(1, 3)))
    console.print()

def _shutdown(reason="quit", code=0):
    """Print the sign-off at most once, hand the cursor back, and exit."""
    global _FAREWELL_SHOWN
    console.show_cursor(True)
    if not _FAREWELL_SHOWN:
        _FAREWELL_SHOWN = True
        _farewell(reason)
    sys.exit(code)

def interactive_menu():
    """Live dashboard: refreshes itself while you decide what to do."""
    shortcuts = [
        ("d", "Doctor"), ("s", "Sync"), ("p", "Pair"), ("q", "Pair QR"),
        ("f", "Discover"), ("n", "Scan"), ("a", "Add app"),
        ("+", "Add device"), ("e", "Edit device"), ("-", "Delete device"),
        ("g", "Toggle device"),
        ("m", "Rename device"), ("b", "Bind all ports"), ("r", "Batch screenshot"),
        ("c", "Edit config"),
    ]
    handlers = {
        "d": action_doctor, "s": action_sync, "p": action_pair, "q": action_pair_qr,
        "f": action_discover, "n": action_scan, "a": lambda: action_add_app(),
        "b": lambda: action_bind("all", "all"),
        "r": lambda: action_media("all", "screenshot"),
        "+": action_add_device, "e": action_edit_device, "-": action_delete_device,
        "g": action_toggle_device, "m": _rename_device_prompt,
        "c": _open_config_in_editor,
    }
    # The dashboard is re-rendered on every refresh, so the index maps are
    # captured here rather than passed around.
    indices = {}
    state = {"cursor": 0}

    def body():
        # One batch telemetry read warms the cache, so the rows built below are
        # cheap even though the screen refreshes itself on a timer.
        get_device_telemetry_parallel(sorted(get_connected_device_ids()))
        if DEVICES and APPS:
            return None
        # Nothing set up yet: one card that says what to do, instead of empty
        # sections the user has to interpret.
        hints = []
        if not DEVICES:
            hints.append(Text.from_markup(
                "  [bold bright_white]Plug in a phone[/bold bright_white] then run "
                "[bold cyan]Doctor[/bold cyan] — it finds USB devices and asks for a name."))
        else:
            hints.append(Text.from_markup(
                f"  [bold bright_white]{_plural(len(DEVICES), 'device')}[/bold bright_white] "
                "registered — press [bold cyan]p[/bold cyan] to pair another over Wi-Fi."))
        if not APPS:
            hints.append(Text.from_markup(
                "  [bold bright_white]Point fenox at your projects[/bold bright_white] with "
                "[bold cyan]Scan[/bold cyan] for a whole directory, or "
                "[bold cyan]Add app[/bold cyan] for one."))
        return Panel(Group(*hints), box=box.ROUNDED, border_style="yellow",
                     title=Text("GETTING STARTED", style="yellow"), title_align="left",
                     padding=(0, 1))

    def counters():
        """Right-hand side of the header bar: how much is set up."""
        return (f"[bold bright_white]{_plural(len(DEVICES), 'device')}[/bold bright_white]"
                f"   [dim]│[/dim]   "
                f"[bold bright_white]{_plural(len(APPS), 'app')}[/bold bright_white]")

    def reach():
        """Footer status: what is reachable right now, refreshed with the screen."""
        online, total = len(get_connected_device_ids()), len(DEVICES)
        if not total:
            state = "[yellow]●[/yellow] [dim]no devices registered[/dim]"
        elif online == total:
            state = f"[green]●[/green] [dim]{online} online[/dim]"
        elif online:
            state = (f"[yellow]●[/yellow] [dim]{online} online · {total - online} offline[/dim]")
        else:
            state = f"[red]●[/red] [dim]all {total} offline[/dim]"
        return f"{state}   [dim]│[/dim]   [dim]adb :{ADB_SERVER_PORT}[/dim]"

    def rows():
        """Devices, then apps, then maintenance — sections of one screen."""
        connected = set(get_connected_device_ids())
        items, dev_index, app_index = [], {}, {}
        if DEVICES:
            items.append((None, "DEVICES"))
        for number, (name, info) in enumerate(DEVICES.items(), start=1):
            dev_index[str(number)] = name
            items.append((str(number), *_device_row(name, info, connected)))
        if APPS:
            items.append((None, "APPS"))
        for number, (name, data) in enumerate(APPS.items(), start=len(DEVICES) + 1):
            app_index[str(number)] = name
            items.append((str(number), *_app_row(name, data)))
        items.append((None, "ACTIONS", "", 2))
        items.extend((key, label, "", 2) for key, label in shortcuts)
        indices["dev"], indices["app"] = dev_index, app_index
        return items

    while True:
        choice = run_menu(
            options=rows,
            body=body,
            subtitle=lambda: f"{_platform_label()} · live dashboard · refreshes every 5s",
            breadcrumb=counters,
            status=reach,
            footer=("[dim]↑/↓ or a number   [bold bright_white]Enter[/bold bright_white] open   "
                    "[bold bright_white]x[/bold bright_white] quit[/dim]"),
            interval=5.0,
            accent="bright_cyan",
            back_keys=("x", "esc"),
            state=state,
            two_col=True,
        )
        if choice is None:
            return
        if choice in indices.get("dev", {}):
            device_actions(indices["dev"][choice])
            continue
        if choice in indices.get("app", {}):
            app_actions(indices["app"][choice])
            continue
        handler = handlers.get(choice)
        if handler:
            handler()
            _wait_any_key("press Enter to return to the dashboard")

# --- Main Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="fenox")
    subparsers = parser.add_subparsers(dest="command")
    
    parser_run = subparsers.add_parser("run")
    parser_run.add_argument("app")
    parser_run.add_argument("device")
    parser_run.add_argument("--remote", action="store_true")
    
    parser_bind = subparsers.add_parser("bind")
    parser_bind.add_argument("app")
    parser_bind.add_argument("device")
    
    parser_connect = subparsers.add_parser("connect")
    parser_connect.add_argument("device", nargs="?", default="all")
    
    parser_rename = subparsers.add_parser("rename")
    parser_rename.add_argument("device")
    parser_rename.add_argument("name", nargs="?")
    
    parser_logs = subparsers.add_parser("logs")
    parser_logs.add_argument("app")
    parser_logs.add_argument("device")
    
    parser_nuke = subparsers.add_parser("nuke")
    parser_nuke.add_argument("app")
    parser_nuke.add_argument("device")
    
    parser_mirror = subparsers.add_parser("mirror")
    parser_mirror.add_argument("device")
    
    parser_screenshot = subparsers.add_parser("screenshot")
    parser_screenshot.add_argument("device")
    
    parser_record = subparsers.add_parser("record")
    parser_record.add_argument("device")
    
    parser_build = subparsers.add_parser("build")
    parser_build.add_argument("app")
    
    subparsers.add_parser("doctor")
    subparsers.add_parser("sync")
    subparsers.add_parser("discover")
    parser_addapp = subparsers.add_parser("add-app")
    parser_addapp.add_argument("--name")
    parser_addapp.add_argument("--path")
    parser_addapp.add_argument("--port")
    parser_addapp.add_argument("--api-local")
    parser_addapp.add_argument("--api-remote")
    parser_addapp.add_argument("--socket-local")
    parser_addapp.add_argument("--socket-remote")
    parser_addapp.add_argument("--additional-ports")
    parser_addapp.add_argument("--backend-path")
    parser_addapp.add_argument("--backend-cmd")
    parser_addapp.add_argument("--update", action="store_true")
    parser_addapp.add_argument("--yes", action="store_true")
    parser_scan = subparsers.add_parser("scan")
    parser_scan.add_argument("--dry-run", action="store_true")
    parser_backend = subparsers.add_parser("backend")
    parser_backend.add_argument("app")
    parser_hot = subparsers.add_parser("hot")
    parser_hot.add_argument("app")
    parser_hot.add_argument("--full", action="store_true")
    parser_install = subparsers.add_parser("install")
    parser_install.add_argument("app")
    parser_open = subparsers.add_parser("open")
    parser_open.add_argument("app")
    parser_open.add_argument("device")
    subparsers.add_parser("pair")
    subparsers.add_parser("pair-qr")
    parser_devices = subparsers.add_parser("devices", help="List devices with live status")
    parser_devices.add_argument("--json", dest="json_out", action="store_true")
    parser_profile = subparsers.add_parser("profile", help="Export/import your fenox setup")
    parser_profile.add_argument("action", choices=["export", "import", "list"])
    parser_profile.add_argument("name", nargs="?")
    parser_watch = subparsers.add_parser("watch", help="Auto-rebind reverse ports on device (re)plug")
    parser_watch.add_argument("--interval", type=int, default=3)
    subparsers.add_parser("update", help="Self-update fenox from the installer script")
    parser_init = subparsers.add_parser("init", help="One-time setup: environment, project directory, shell hooks")
    parser_init.add_argument("--reset-settings", action="store_true", help="Ask the one-time questions again")
    parser_uninstall = subparsers.add_parser("uninstall", help="Remove fenox, its config and its shell hooks")
    parser_uninstall.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    parser_uninstall.add_argument("--keep-config", action="store_true", help="Leave ~/.fenox.json in place")
    parser_groups = subparsers.add_parser("groups", help="Manage device groups (use as @name in run)")
    parser_groups.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    parser_groups.add_argument("name", nargs="?")
    parser_groups.add_argument("members", nargs="*")
    parser_phone = subparsers.add_parser("phone", help="Read your phone's own data: messages, calls, contacts, calendar")
    parser_phone.add_argument("resource", nargs="?", default="messages", choices=list(PHONE_RESOURCES))
    parser_phone.add_argument("--device", help="Device alias or adb id (default: the only connected one)")
    parser_phone.add_argument("--thread", help="Show one conversation, by the Thread id listed")
    parser_phone.add_argument("--search", help="Messages whose body, or calls whose number or name, contains this text")
    parser_phone.add_argument("--unread", action="store_true", help="Only threads with unread messages")
    parser_phone.add_argument("--limit", type=int, default=25, help="Rows to show (default 25)")
    parser_phone.add_argument("--mark-read", action="store_true", help="Mark the shown thread read, or the shown calls as seen, on the phone")
    parser_phone.add_argument("--export", metavar="FILE", help="Write the result to a local file")
    parser_phone.add_argument("--redact", action="store_true", help="Hide numbers and message bodies")
    parser_phone.add_argument("--missed", action="store_true", help="Calls: only the ones that were missed")
    parser_phone.add_argument("--incoming", action="store_true", help="Calls: only the ones that came in")
    parser_phone.add_argument("--outgoing", action="store_true", help="Calls: only the ones you dialled")
    parser_phone.add_argument("--from", dest="from_number", metavar="NUMBER", help="Calls: the history with this number or contact name")
    parser_phone.add_argument("--days", type=int, default=30, help="Calls: how far back to look; 0 is the whole log (default 30)")
    parser_phone.add_argument("--dial", action="store_true", help="Calls: place the call to --from now, after confirming")
    parser_phone.add_argument("--at", metavar="TIME", help="Calendar --add: `HH:MM` (today/tomorrow) or `YYYY-MM-DD HH:MM`")
    parser_phone.add_argument("--add", metavar="TITLE", help="Calendar: add an event with this title (needs --at)")
    parser_phone.add_argument("--duration", type=int, default=60, help="Calendar --add: length in minutes (default 60)")
    parser_phone.add_argument("--json", dest="json_out", action="store_true", help="Machine-readable output")
    parser.add_argument("--version", action="version", version=f"fenox {FENOX_VERSION}")
    parser.add_argument("--generate-completions", metavar="SHELL", choices=["bash", "zsh"], help=argparse.SUPPRESS)

# --- Clean exits: no tracebacks on Ctrl+C or piped/EOF input -----------------
def _interrupted():
    """Ctrl+C: close a session with its sign-off, or just say so and exit 130."""
    console.show_cursor(True)
    if _SESSION_OPENED:
        _shutdown("interrupt", 130)
    console.print("\n[bold cyan]👋 Interrupted — nothing was left running.[/bold cyan]")
    sys.exit(130)

def _main():
    try:
        # Sourcing a shell must stay instant and side-effect free: no adb server,
        # no config writes, nothing a new terminal has to wait for.
        if "--generate-completions" in sys.argv:
            idx = sys.argv.index("--generate-completions")
            shell = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "bash"
            generate_completions(shell)
            return
        # `fenox <plugin>` — anything that is neither a built-in nor a flag.
        if (len(sys.argv) > 1 and not sys.argv[1].startswith("-")
                and sys.argv[1] not in KNOWN_COMMANDS):
            ensure_shared_adb_server()
            action_plugin(sys.argv[1], sys.argv[2:])
            return
        args = parser.parse_args()   # --version / --help exit here, without adb
        if args.command is None:
            _session_start()
            try:
                interactive_menu()
            finally:
                # The live view hides the cursor; always hand it back, even on Ctrl+C.
                console.show_cursor(True)
            _shutdown("quit", 0)
        ensure_shared_adb_server()
        _dispatch(args)
    except KeyboardInterrupt:
        _interrupted()
    except EOFError:
        if _SESSION_OPENED:
            _shutdown("eof", 0)
        console.print("\n[dim]Input ended — exiting.[/dim]")
        sys.exit(0)

def _dispatch(args):
    if args.command == "doctor": action_doctor()
    elif args.command == "sync": action_sync()
    elif args.command == "discover": action_discover()
    elif args.command == "add-app": action_add_app(args)
    elif args.command == "scan": action_scan(args)
    elif args.command == "backend": action_backend(args.app)
    elif args.command == "hot": action_hot(args.app, full=args.full)
    elif args.command == "install": action_install(args.app)
    elif args.command == "open": action_open(args.app, args.device)
    elif args.command == "pair": action_pair()
    elif args.command == "pair-qr": action_pair_qr()
    elif args.command == "bind": action_bind(args.app, args.device)
    elif args.command == "connect": action_connect(args.device)
    elif args.command == "rename": action_rename_device(args.device, args.name)
    elif args.command == "devices": action_devices(json_out=args.json_out)
    elif args.command == "profile": action_profile(args.action, args.name)
    elif args.command == "watch": action_watch(interval=args.interval)
    elif args.command == "update": action_update()
    elif args.command == "groups": action_groups(args.action, args.name, args.members)
    elif args.command == "init": action_init(reset=args.reset_settings)
    elif args.command == "uninstall": action_uninstall(args)
    elif args.command == "build": action_build(args.app)
    elif args.command == "mirror": action_mirror(args.device)
    elif args.command == "screenshot": action_media(args.device, "screenshot")
    elif args.command == "record": action_media(args.device, "record")
    elif args.command == "logs": action_logs(args.app, args.device)
    elif args.command == "nuke": action_nuke(args.app, args.device)
    elif args.command == "run": action_run(args.app, args.device, args.remote)
    elif args.command == "phone": action_phone(args)

# --- Run ----------------------------------------------------------------------
if __name__ == "__main__":
    if "--generate-aliases" in sys.argv:
        generate_aliases()
    else:
        _main()

