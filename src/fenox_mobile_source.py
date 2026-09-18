#!/usr/bin/env python3
import os, subprocess, sys, json, argparse, shutil, datetime, time, secrets, string, re, signal
from pathlib import Path
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.live import Live

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
FENOX_VERSION = "1.0.0"
KNOWN_COMMANDS = {"run", "bind", "connect", "rename", "logs", "nuke", "mirror", "screenshot", "record", "build", "doctor", "sync", "discover", "add-app", "scan", "backend", "hot", "install", "open", "pair", "pair-qr", "devices", "profile", "watch", "update", "groups", "init", "uninstall"}
IS_WINDOWS = sys.platform == "win32"
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
        out = subprocess.run(["/mnt/c/Windows/System32/cmd.exe", "/c", "echo %USERNAME%"], capture_output=True, text=True, timeout=6).stdout.strip()
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
        out = subprocess.run(["/mnt/c/Windows/System32/cmd.exe", "/c", "where adb"], capture_output=True, text=True, timeout=6).stdout.strip().splitlines()
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
            capture_output=True, text=True, timeout=8,
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
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
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
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except: return ""

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

def discover_wireless_debug_ports(target_ip):
    if not shutil.which("nmap"):
        return []

    output = run_cmd(f"timeout 10 nmap -p 37000-44000 {target_ip} --open -T4 --host-timeout 8s")
    ports = []
    for line in output.splitlines():
        if "/tcp" not in line or "open" not in line:
            continue
        port = line.split("/")[0].strip()
        if port.isdigit():
            ports.append(port)
    return ports

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
  1. 📸 [bold]fenox-mobile pair-qr[/bold] — QR code method (recommended)
  2. 🔢 [bold]fenox-mobile pair[/bold] — Manual pairing code
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
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
  4. If scanning doesn't work, use [bold]fenox-mobile pair[/bold] instead (manual code)

[cyan]Your PC IP: {pc_ip}
ADB Port: {adb_port}
Password: {password}[/cyan]
""")

# --- Scrcpy Mirroring ---
def action_mirror(dev_key):
    if not shutil.which("scrcpy") and not os.path.exists("/usr/bin/scrcpy"):
        console.print("[red]❌ 'scrcpy' is not installed. Please install it to use mirroring.[/red]")
        return
    dev_id = check_and_connect(dev_key, interactive=True)
    if not dev_id: return
    console.print(f"[green]📱 Launching mirror for {dev_key.upper()}...[/green]")
    scrcpy_bin = shutil.which("scrcpy") or "/usr/bin/scrcpy"
    subprocess.Popen([scrcpy_bin, "-s", dev_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- Doctor: auto-discover and connect devices ---------------------------------
# Use 'fenox-mobile sync' to reconnect known devices, or 'fenox-mobile pair' to add new ones.

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
        subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", f"Start-Process '{win_filepath}'"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-sta", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    """Manage device groups: fenox-mobile groups add testers s21+ s21+usb"""
    groups = config.setdefault("groups", {})
    if action in (None, "list"):
        if not groups:
            console.print("[yellow]No groups yet. Create one:[/yellow] fenox-mobile groups add testers s21+ itel")
            return
        t = Table(title="Device Groups", box=box.ROUNDED)
        t.add_column("Group"); t.add_column("Members")
        for g, ms in groups.items():
            t.add_row(f"@{g}", ", ".join(ms))
        console.print(t)
        return
    if action == "add":
        if not name or not members:
            console.print("[red]Usage: fenox-mobile groups add <group> <device1> [device2 ...][/red]"); return
        bad = [m for m in members if m not in DEVICES]
        if bad:
            console.print(f"[red]❌ Unknown device(s): {', '.join(bad)}. Known: {', '.join(DEVICES.keys())}[/red]"); return
        groups[name] = sorted(set(groups.get(name, [])) | set(members))
        save_config()
        console.print(f"[green]✅ Group @{name}: {', '.join(groups[name])}[/green]")
        console.print(f"[dim]Run on the whole group: fenox-mobile run <app> @{name}[/dim]")
    elif action == "remove":
        if not name or name not in groups:
            console.print(f"[red]❌ Unknown group: {name}. Existing: {', '.join(groups.keys()) or 'none'}[/red]"); return
        del groups[name]
        save_config()
        console.print(f"[green]✅ Group @{name} removed.[/green]")
    else:
        console.print("[red]Usage: fenox-mobile groups [list|add|remove] ...[/red]")

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
        for candidate in (os.path.expanduser("~/.local/bin/fenox-mobile"), "/usr/local/bin/fenox-mobile"):
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
            if os.path.exists(rc) and "# fenox-mobile" in open(rc, encoding="utf-8", errors="ignore").read():
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
                if line.lstrip().startswith("# fenox-mobile"):
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
    plat = "Windows" if IS_WINDOWS else ("WSL" if IS_WSL else ("macOS" if IS_MACOS else "Linux"))
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
    if IS_WINDOWS:
        hints = {"adb": "install Android platform-tools and add adb.exe to your PATH",
                 "scrcpy": "winget install Genymobile.scrcpy",
                 "tmux": "not available on Windows — blast deploys run one device at a time",
                 "flutter": "see https://docs.flutter.dev/get-started/install/windows"}
        optional = {"tmux"}
    elif IS_MACOS:
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
    if IS_WINDOWS:
        console.print()
        console.print("[dim]Windows: aliases and completions are a bash/zsh feature. Run fenox from "
                      "PowerShell, or use the raw CLI commands (fenox-mobile run <app> <device>).[/dim]")
    elif sys.stdin.isatty():
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
                    f.write(f"\n# fenox-mobile {label}\n{line}\n")
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
        print(f"""#compdef fenox fenox-mobile
# fenox-mobile zsh completion
_fenox() {{
  local -a cmds
  cmds=({zcmds})
  if (( CURRENT == 2 )); then
    _describe 'command' cmds
  fi
}}
compdef _fenox fenox fenox-mobile 2>/dev/null""")
    else:
        print(f"""# fenox-mobile bash completion
_fenox_completions() {{
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{cmds}" -- "${{COMP_WORDS[COMP_CWORD]}}") )
    fi
}}
complete -o default -F _fenox_completions fenox-mobile 2>/dev/null
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

def action_update():
    """Self-update from GitHub releases (or local repo build as fallback)."""
    console.print(Panel.fit("[bold cyan]⬆️ FENOX SELF-UPDATE[/bold cyan]", border_style="cyan"))
    current = FENOX_VERSION
    console.print(f"[cyan]Current version:[/cyan] {current}")

    latest = None
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/onefennox/fenox-mobile/releases/latest",
            headers={"User-Agent": "fenox-mobile-updater", "Accept": "application/vnd.github+json"},
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
    repo_install = os.path.expanduser("~/Projects/fenox-mobile/install.sh")
    repo_ver = None
    if os.path.exists(repo_install):
        try:
            repo_ver = open(os.path.join(os.path.dirname(repo_install), "VERSION")).read().strip()
        except Exception:
            repo_ver = None
    if latest and repo_ver and _ver_key(repo_ver) < _ver_key(latest):
        console.print(f"[yellow]Local repo is v{repo_ver} — older than release v{latest}. Downloading instead.[/yellow]")
    elif os.path.exists(repo_install):
        if not Confirm.ask("Rebuild+install from the local repo (~/Projects/fenox-mobile)?", default=True):
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
    asset = f"fenox-mobile-linux-{arch}"
    base = f"https://github.com/onefennox/fenox-mobile/releases/download/v{latest}"
    tmp_bin = f"/tmp/fenox-mobile.update.{os.getpid()}"
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
        console.print("[red]Usage: fenox-mobile profile export|import|list [name][/red]"); return
    prof_dir = os.path.expanduser("~/.fenox/profiles")
    os.makedirs(prof_dir, exist_ok=True)
    if action == "list":
        profiles = sorted(os.listdir(prof_dir))
        if not profiles:
            console.print("[yellow]No profiles yet. Create one:[/yellow] fenox-mobile profile export mysetup")
            return
        t = Table(title="Fenox Profiles", box=box.ROUNDED)
        t.add_column("Profile"); t.add_column("Created")
        for p in profiles:
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(prof_dir, p)))
            t.add_row(p.replace(".json", ""), mt.strftime("%Y-%m-%d %H:%M"))
        console.print(t)
        return
    if not profile_name:
        console.print("[red]Profile name required: fenox-mobile profile export|import <name>[/red]"); return
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
            console.print("[dim]Copy it to another machine, then: fenox-mobile profile import " + profile_name + "[/dim]")
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
        console.print("[green]✅ Profile imported. Run 'fenox-mobile doctor' to verify.[/green]")

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
        console.print("[bold red]🔥 QUICK CRASH TRIAGE — fenox-mobile logs " + app_key + " " + dev_key + " --last-crash[/bold red]")
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
                console.print(f"[dim]ℹ️  Unknown device connected: {d_id} (use 'fenox-mobile pair' to add it)[/dim]")
    
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
        
        os.system(f"tmux new-session -d -s {session} 'fenox-mobile run {app_key} {online[0]} {remote_flag}'")
        os.system(f"tmux set-option -g mouse on")
        for dev in online[1:]:
            os.system(f"tmux split-window -h -t {session} 'fenox-mobile run {app_key} {dev} {remote_flag}'")
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
        print(f'alias {app}-release="fenox-mobile build {app}"')
        print(f'alias {app}-all="fenox-mobile run {app} all"')
        print(f'alias {app}-all-remote="fenox-mobile run {app} all --remote"')
        for dev in DEVICES:
            print(f'alias {app}-{dev}="fenox-mobile run {app} {dev}"')
            print(f'alias {app}-{dev}-remote="fenox-mobile run {app} {dev} --remote"')
            print(f'alias {app}-{dev}-bind="fenox-mobile bind {app} {dev}"')
            print(f'alias {app}-{dev}-logs="fenox-mobile logs {app} {dev}"')
            print(f'alias {app}-{dev}-nuke="fenox-mobile nuke {app} {dev}"')
            
    for app in APPS:
        print(f'alias {app}-backend="fenox-mobile backend {app}"')
        print(f'alias {app}-hot="fenox-mobile hot {app}"')
        print(f'alias {app}-install="fenox-mobile install {app}"')
    for dev in DEVICES:
        print(f'alias {dev}-mirror="fenox-mobile mirror {dev}"')
        print(f'alias {dev}-screenshot="fenox-mobile screenshot {dev}"')
        print(f'alias {dev}-record="fenox-mobile record {dev}"')
    
    print('alias fenox-add-app="fenox-mobile add-app"')
    print('alias fenox-scan="fenox-mobile scan"')
    print('alias fenox-bind-all="fenox-mobile bind all all"')
    print('alias fenox-connect="fenox-mobile connect"')
    print('alias fenox-rename="fenox-mobile rename"')
    print('alias fenox-doctor="fenox-mobile doctor"')
    print('alias fenox-sync="fenox-mobile sync"')
    print('alias fenox-discover="fenox-mobile discover"')
    print('alias fenox-pair="fenox-mobile pair"')
    print('alias fenox-pair-qr="fenox-mobile pair-qr"')
    print('alias fenox-shot-all="fenox-mobile screenshot all"')
    print('alias fenox-reload="source ~/.zshrc"')
    # --- Live alias auto-reload: re-eval aliases whenever ~/.fenox.json changes ---
    # Installed once via the same `eval "$(fenox-mobile --generate-aliases)"` line.
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
    print('      eval "$(fenox-mobile --generate-aliases 2>/dev/null)"')
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
# Menus respond to a single keypress, which needs the terminal in raw mode.
# Everything degrades to line input when stdin is not a TTY, so piped input, CI
# and dumb terminals keep working.
try:
    import termios as _termios
    import tty as _tty
except ImportError:
    _termios = _tty = None
try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

_ESCAPE_KEYS = {"\x1b[A": "UP", "\x1b[B": "DOWN", "\x1b[C": "RIGHT", "\x1b[D": "LEFT"}
_WIN_ARROWS = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT"}

def _read_key(timeout=None):
    """Read one keypress without waiting for Enter.

    Returns a single lowercased character, or one of UP/DOWN/LEFT/RIGHT/ESC/
    ENTER/BACKSPACE. Returns None on timeout, or immediately when stdin is not an
    interactive terminal.
    """
    if not sys.stdin.isatty():
        return None

    if _msvcrt is not None:                    # Windows console
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if _msvcrt.kbhit():
                ch = _msvcrt.getwch()
                if ch in ("\x00", "\xe0"):     # arrow / function key prefix
                    return _WIN_ARROWS.get(_msvcrt.getwch(), "")
                if ch == "\r": return "ENTER"
                if ch == "\x1b": return "ESC"
                if ch == "\x08": return "BACKSPACE"
                if ch == "\x03": raise KeyboardInterrupt
                return ch.lower()
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.03)

    if _termios is None:
        return None

    import select
    fd = sys.stdin.fileno()
    old = _termios.tcgetattr(fd)
    try:
        _tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        ch = sys.stdin.read(1)
    finally:
        _termios.tcsetattr(fd, _termios.TCSADRAIN, old)

    if ch == "\x1b":                           # maybe an escape sequence
        ready, _, _ = select.select([sys.stdin], [], [], 0.02)
        if ready:
            rest = sys.stdin.read(2)
            return _ESCAPE_KEYS.get("\x1b" + rest, "ESC")
        return "ESC"
    if ch in ("\r", "\n"): return "ENTER"
    if ch in ("\x7f", "\x08"): return "BACKSPACE"
    if ch == "\x03": raise KeyboardInterrupt
    return ch.lower()

def _wait_any_key(hint="press any key to continue"):
    """Let the user read an action's output, then continue without needing Enter."""
    if not sys.stdin.isatty():
        return
    console.print(f"\n  [dim]{hint}…[/dim]")
    try:
        _read_key()
    except KeyboardInterrupt:
        pass

def _ask_key(prompt="select", default="b"):
    """One-keypress selector. Falls back to a line prompt when stdin is not a TTY."""
    if not sys.stdin.isatty():
        return Prompt.ask(f"▸ [dim]{prompt}[/dim]", default=default).lower()
    console.print(f"  [bold bright_white]▸[/bold bright_white] "
                  f"[dim]{prompt} — one key, [bold]{default}[/bold] = back[/dim]")
    try:
        key = _read_key()
    except KeyboardInterrupt:
        return default
    if key in (None, "esc"):
        return default
    return str(key).lower()

def _menu_renderable(title, options, body, breadcrumb, subtitle, footer, accent):
    """Assemble the pieces of a menu screen into one renderable."""
    parts = []
    if breadcrumb:
        parts.append(Text.from_markup(f"  [dim]{breadcrumb}[/dim]"))
    if body is not None:
        parts.append(body() if callable(body) else body)
    if title:
        parts.append(Panel(f"[bold bright_white]{title}[/bold bright_white]",
                           box=box.HEAVY, border_style=accent, padding=(0, 1)))
    if subtitle:
        parts.append(Text.from_markup(f"  [dim]{subtitle}[/dim]"))
    if options:
        grid = Table.grid(padding=(0, 3))
        columns = 2 if len(options) > 5 else 1
        for _ in range(columns):
            grid.add_column()
        for i in range(0, len(options), columns):
            row = [f"[bold {accent}]{k}[/bold {accent}] [dim]{label}[/dim]"
                   for k, label in options[i:i + columns]]
            while len(row) < columns:
                row.append("")
            grid.add_row(*row)
        parts.append(grid)
    parts.append(Text.from_markup(footer))
    return Group(*parts)

def run_menu(title=None, options=(), *, body=None, breadcrumb="", subtitle=None,
             footer=None, interval=0.0, accent="bright_cyan",
             back_keys=("b", "esc")):
    """Draw a menu, wait for one keypress, and return the key that was chosen.

    options   : list of (key, label) shown as a grid of hints
    body      : renderable (or callable returning one) drawn above the options
    interval  : seconds between automatic refreshes; >0 makes the screen live
    back_keys : keys meaning "go back"; returns None for those

    Unknown keys are ignored without an error message or an Enter press.
    """
    valid = [str(k).lower() for k, _ in options]
    draw = lambda: _menu_renderable(title, options, body, breadcrumb, subtitle,
                                    footer or "  [bold bright_red]b[/bold bright_red] [dim]back[/dim]",
                                    accent)

    if not sys.stdin.isatty():                 # scripts, pipes, dumb terminals
        console.print(draw())
        # Offer whichever back key is not already an option, so piping input can
        # never silently fire a short-cut ("b" means bind, not back, on the main menu).
        back = next((k for k in back_keys if k and k not in valid), "b")
        answer = Prompt.ask("▸", choices=valid + [back], default=back).lower()
        return None if answer in back_keys else answer

    if interval and interval > 0:
        with Live(draw(), console=console, screen=True, refresh_per_second=4) as live:
            nxt = time.monotonic() + interval
            while True:
                key = _read_key(timeout=0.2)
                if key is not None:
                    break
                if time.monotonic() >= nxt:
                    live.update(draw())
                    nxt = time.monotonic() + interval
    else:
        console.print(draw())
        key = _read_key()

    if key is None:
        return None
    if key in back_keys:
        return None
    if not valid or key in valid:
        return key
    return ""                                  # unknown key → caller redraws

def _banner():
    """Header banner with live summary stats, as a renderable."""
    connected_ids = set(get_connected_device_ids())
    online_count = 0
    for key, info in DEVICES.items():
        if info.get("type") == "emulator":
            if any(cid.startswith("emulator-") for cid in connected_ids):
                online_count += 1
        elif is_device_enabled(info):
            if any(info.get("ip", "") in cid for cid in connected_ids):
                online_count += 1
    total_devices = len(DEVICES)
    total_apps = len(APPS)
    enabled_devices = sum(1 for info in DEVICES.values() if is_device_enabled(info))
    offline_count = enabled_devices - online_count
    disabled_count = total_devices - enabled_devices
    stats = []
    if online_count > 0:
        stats.append(f"[green]● {online_count} online[/green]")
    if offline_count > 0:
        stats.append(f"[red]● {offline_count} offline[/red]")
    if disabled_count > 0:
        stats.append(f"[yellow]● {disabled_count} disabled[/yellow]")
    stats_str = "   ".join(stats)
    header = Text.from_markup(
        f"[bold bright_white]⚡ FENOX MOBILE[/bold bright_white]"
        f"  [dim bright_white]│[/dim bright_white]  "
        f"[bright_cyan]ENVIRONMENT MANAGER[/bright_cyan]"
        f"  [dim bright_white]│[/dim bright_white]  "
        f"[bold]{total_devices}[/bold] [dim]devices[/dim]  [dim]•[/dim]  "
        f"[bold]{total_apps}[/bold] [dim]apps[/dim]"
    )
    parts = [Panel(header, box=box.HEAVY, border_style="bright_blue", padding=(0, 1))]
    if stats_str:
        parts.append(Text.from_markup(f"  {stats_str}"))
    return Group(*parts)
    console.print()

def _build_dashboard():
    """Pure render of the dashboard: (renderable, dev_index, app_index)."""
    _parts = []
    connected_ids = set(get_connected_device_ids())
    dev_table = Table(
        box=box.ROUNDED, header_style="bold bright_cyan",
        border_style="dim blue", show_header=True, pad_edge=True, expand=False,
        title="[bold bright_cyan]📱 DEVICES[/bold bright_cyan]", title_style="bold",
    )
    dev_table.add_column("#", style="dim", width=3, justify="right")
    dev_table.add_column("Alias", style="bold bright_white", min_width=10)
    dev_table.add_column("Model", style="dim white", min_width=16)
    dev_table.add_column("Address", style="dim", min_width=18)
    dev_table.add_column("Status", min_width=12)
    dev_table.add_column("Battery", justify="center", min_width=7)
    dev_table.add_column("Screen", justify="center", min_width=8)
    dev_table.add_column("Android", justify="center", min_width=8)
    dev_table.add_column("Storage", justify="center", min_width=8)
    dev_table.add_column("Foreground", min_width=12)
    dev_table.add_column("Health", justify="center", width=6)
    dev_index = {}
    idx = 1
    for key, info in DEVICES.items():
        d_id = None
        if info.get("type") == "emulator":
            for cid in connected_ids:
                if cid.startswith("emulator-"):
                    d_id = cid
                    break
            addr = f"emulator:{info.get('port', '')}"
        elif not is_device_enabled(info):
            dev_table.add_row(
                f"[dim]{idx}[/dim]", key, str(info.get("model", "?")),
                f"[dim]{info.get('ip') or info.get('serial') or info.get('port') or '?'}[/dim]",
                "[yellow]⏭ Disabled[/yellow]", "", "", "", "", "", "[yellow]—[/yellow]"
            )
            dev_index[idx] = key
            idx += 1
            continue
        elif info.get("type") == "usb":
            addr = f"usb:{info.get('serial', '')}"
            for cid in connected_ids:
                if cid == info.get("serial"):
                    d_id = cid
                    break
        else:
            addr = f"{info.get('ip', '')}:{info.get('port', '')}"
            for cid in connected_ids:
                if info.get("ip", "") in cid:
                    d_id = cid
                    break
        if d_id:
            tele = get_device_telemetry(d_id)
            batt = str(tele.get("battery", "?"))
            try:
                b = int(batt)
                if b <= 15:
                    batt_str, health = f"[bold red]{batt}%[/bold red]", "[bold red]🔴[/bold red]"
                elif b <= 30:
                    batt_str, health = f"[yellow]{batt}%[/yellow]", "[yellow]🟡[/yellow]"
                else:
                    batt_str, health = f"[green]{batt}%[/green]", "[green]🟢[/green]"
                if tele.get("charging"):
                    batt_str += " ⚡"
            except (ValueError, TypeError):
                batt_str, health = f"[dim]{batt}[/dim]", "[dim]⚪[/dim]"
            screen = tele.get("screen", "?")
            screen_str = f"[green]☀ {screen}[/green]" if screen == "On" else f"[dim]☾ {screen}[/dim]"
            dev_table.add_row(
                f"[dim]{idx}[/dim]", key,
                f"[bright_white]{info.get('model', '?')}[/bright_white]",
                f"[dim]{addr}[/dim]",
                "[bold green]● Online[/bold green]",
                batt_str, screen_str,
                f"[cyan]{tele.get('android', '?')}[/cyan]",
                f"[dim]{tele.get('storage', '?')}[/dim]",
                f"[dim]{tele.get('app', '?')}[/dim]",
                health,
            )
        else:
            dev_table.add_row(
                f"[dim]{idx}[/dim]", key, f"[dim]{info.get('model', '?')}[/dim]",
                f"[dim]{addr}[/dim]", "[bold red]● Offline[/bold red]",
                "[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]",
                "[dim]—[/dim]", "[dim]—[/dim]", "[red]🔴[/red]",
            )
        dev_index[idx] = key
        idx += 1
    _parts.append(dev_table)

    app_table = Table(
        box=box.ROUNDED, header_style="bold bright_green",
        border_style="dim green", show_header=True, pad_edge=True, expand=False,
        title="[bold bright_green]📦 APPS[/bold bright_green]", title_style="bold",
    )
    app_table.add_column("#", style="dim", width=3, justify="right")
    app_table.add_column("App", style="bold bright_white", min_width=16)
    app_table.add_column("Git", min_width=22)
    app_table.add_column("Package", style="dim", min_width=10)
    app_table.add_column("Last Run", min_width=18)
    app_index = {}
    idx = 1
    for key, data in APPS.items():
        pkg = data.get("package") or resolve_package(key) or "?"
        last = get_last_run(key)
        last_str = "[dim]—[/dim]"
        if last:
            ago = _human_ago(last.get("ts", ""))
            ok = last.get("ok", False)
            action = last.get("action", "?")
            if ok:
                last_str = f"[green]{ago}[/green] [dim]({action}, ✓)[/dim]"
            else:
                last_str = f"[yellow]{ago}[/yellow] [dim]({action}, ✗)[/dim]"
        git = _git_status(os.path.expanduser(data.get("path", "")))
        app_table.add_row(
            f"[dim]{idx}[/dim]", f"[bright_white]{key}[/bright_white]",
            git, f"[dim]{pkg}[/dim]", last_str,
        )
        app_index[idx] = key
        idx += 1
    _parts.append(app_table)
    return Group(*_parts), dev_index, app_index

def _open_last_capture(key):
    for media_type, (wsl_dir, win_dir) in [("screenshot", (SHOTS_DIR, WIN_SHOTS_DIR)), ("record", (RECS_DIR, WIN_RECS_DIR))]:
        dev_sub = os.path.join(wsl_dir, key)
        if not os.path.isdir(dev_sub): continue
        files = sorted(Path(dev_sub).glob("*"), key=os.path.getmtime, reverse=True)
        if files:
            _open_in_windows(f"{win_dir}\\{key}\\{files[0].name}")
            console.print(f"[green]🖼 Opened {files[0].name}[/green]")
            return
    console.print("[yellow]No captures found for this device yet.[/yellow]")

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

def _device_header(key):
    """Render the device command center header with live stats."""
    info = DEVICES[key]
    d_id = check_and_connect(key, interactive=False)
    connected = d_id is not None
    model = info.get("model", "?")
    addr = f"{info.get('ip', '')}:{info.get('port', '')}"
    status_str = "[bold green]● ONLINE[/bold green]" if connected else "[bold red]● OFFLINE[/bold red]"
    bat_pct, stor_pct, screen, android = 0, 0, "?", "?"
    if connected:
        tele = get_device_telemetry(d_id)
        try: bat_pct = int(tele.get("battery", "0"))
        except: pass
        try: stor_pct = int(str(tele.get("storage", "0")).replace("%", ""))
        except: pass
        screen = tele.get("screen", "?")
        android = tele.get("android", "?")
    ht = Text.from_markup(
        f"[bold bright_white]⚡ DEVICE COMMAND CENTER[/bold bright_white]\n"
        f"[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]\n"
        f"[bold bright_cyan]📱 {key}[/bold bright_cyan]  [dim]│[/dim]  "
        f"[bright_white]{model}[/bright_white]  [dim]│[/dim]  "
        f"{status_str}  [dim]│[/dim]  Android {android}\n"
        f"[dim]📍[/dim] [dim]{addr}[/dim]  [dim]│[/dim]  "
        f"🔋 {_bar(bat_pct, 12)}  [dim]│[/dim]  "
        f"💾 {_bar(stor_pct, 12)}  [dim]│[/dim]  "
        f"{'☀' if screen == 'On' else '☾'} Screen {screen}"
    )
    console.print(Panel(ht, box=box.HEAVY, border_style="bright_blue", padding=(0, 1)))

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
    body = Prompt.ask("Body", default="Test from fenox-mobile")
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

def _device_screen_menu(key):
    dev_id = check_and_connect(key, interactive=True)
    if not dev_id: return
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]🖥  SCREEN & INPUT — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_cyan", padding=(0, 1)))
        console.print(
            "  [bold bright_cyan]1[/bold bright_cyan] Mirror (scrcpy)     [bold bright_cyan]2[/bold bright_cyan] Screenshot          [bold bright_cyan]3[/bold bright_cyan] Record screen\n"
            "  [bold bright_cyan]4[/bold bright_cyan] Wake screen         [bold bright_cyan]5[/bold bright_cyan] Lock screen         [bold bright_cyan]6[/bold bright_cyan] Type text\n"
            "  [bold bright_cyan]7[/bold bright_cyan] Tap at XY           [bold bright_cyan]8[/bold bright_cyan] Swipe gesture       [bold bright_cyan]9[/bold bright_cyan] Key combos\n"
            "  [bold bright_cyan]A[/bold bright_cyan] Copy text → device  [bold bright_cyan]B[/bold bright_cyan] Read clipboard      [bold bright_cyan]C[/bold bright_cyan] Open URL"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "1": action_mirror(key)
        elif choice == "2": action_media(key, "screenshot")
        elif choice == "3": action_media(key, "record")
        elif choice == "4": run_cmd(f"adb -s {dev_id} shell input keyevent KEYCODE_WAKEUP"); console.print("[green]✅ Screen woken[/green]")
        elif choice == "5": run_cmd(f"adb -s {dev_id} shell input keyevent KEYCODE_SLEEP"); console.print("[green]✅ Screen locked[/green]")
        elif choice == "6": _action_type_text(dev_id)
        elif choice == "7": _action_tap_screen(dev_id)
        elif choice == "8": _action_swipe(dev_id)
        elif choice == "9": _action_key_combo(dev_id)
        elif choice.upper() == "A": _action_clipboard_copy(dev_id)
        elif choice.upper() == "B": _action_clipboard_read(dev_id)
        elif choice.upper() == "C": _action_open_url(dev_id)
        _wait_any_key()

def _device_apps_menu(key):
    dev_id = check_and_connect(key, interactive=True)
    if not dev_id: return
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]📦 APP MANAGEMENT — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_green", padding=(0, 1)))
        console.print(
            "  [bold bright_green]1[/bold bright_green] Open/launch app      [bold bright_green]2[/bold bright_green] List all apps        [bold bright_green]3[/bold bright_green] Uninstall app\n"
            "  [bold bright_green]4[/bold bright_green] Clear app data       [bold bright_green]5[/bold bright_green] Force stop app       [bold bright_green]6[/bold bright_green] App info\n"
            "  [bold bright_green]7[/bold bright_green] Install APK from PC  [bold bright_green]8[/bold bright_green] Nuke + relaunch"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "1":
            if APPS:
                app_key = Prompt.ask("App", choices=list(APPS.keys()))
                action_open(app_key, key)
        elif choice == "2": _action_list_apps(dev_id)
        elif choice == "3": _action_uninstall_app(dev_id)
        elif choice == "4": _action_clear_app_data(dev_id)
        elif choice == "5": _action_force_stop(dev_id)
        elif choice == "6": _action_app_info(dev_id)
        elif choice == "7": _action_install_apk_from_pc(dev_id)
        elif choice == "8":
            if APPS:
                app_key = Prompt.ask("App", choices=list(APPS.keys()))
                action_nuke(app_key, key)
        _wait_any_key()

def _device_files_menu(key):
    dev_id = check_and_connect(key, interactive=True)
    if not dev_id: return
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]📁 FILE MANAGEMENT — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_yellow", padding=(0, 1)))
        console.print(
            "  [bold bright_yellow]1[/bold bright_yellow] Push file to device\n"
            "  [bold bright_yellow]2[/bold bright_yellow] Pull file from device\n"
            "  [bold bright_yellow]3[/bold bright_yellow] Browse device storage"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "1": _action_push_file(dev_id)
        elif choice == "2": _action_pull_file(dev_id)
        elif choice == "3": _action_browse_storage(dev_id)
        _wait_any_key()

def _device_control_menu(key):
    dev_id = check_and_connect(key, interactive=True)
    if not dev_id: return
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]🔧 DEVICE CONTROL — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_magenta", padding=(0, 1)))
        console.print(
            "  [bold bright_magenta]1[/bold bright_magenta] Reboot options      [bold bright_magenta]2[/bold bright_magenta] Toggle WiFi         [bold bright_magenta]3[/bold bright_magenta] Toggle mobile data\n"
            "  [bold bright_magenta]4[/bold bright_magenta] Toggle Bluetooth    [bold bright_magenta]5[/bold bright_magenta] Volume control      [bold bright_magenta]6[/bold bright_magenta] Set brightness\n"
            "  [bold bright_magenta]7[/bold bright_magenta] Interactive shell"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "1": _action_reboot_menu(dev_id)
        elif choice == "2": _action_toggle_wifi(dev_id)
        elif choice == "3": _action_toggle_data(dev_id)
        elif choice == "4": _action_toggle_bluetooth(dev_id)
        elif choice == "5": _action_volume_control(dev_id)
        elif choice == "6": _action_brightness_control(dev_id)
        elif choice == "7": _action_interactive_shell(dev_id)
        _wait_any_key()

def _device_devtools_menu(key):
    dev_id = check_and_connect(key, interactive=True)
    if not dev_id: return
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]🔗 DEV TOOLS — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_white", padding=(0, 1)))
        console.print(
            "  [bold bright_white]1[/bold bright_white] Device info          [bold bright_white]2[/bold bright_white] Battery details      [bold bright_white]3[/bold bright_white] Network info\n"
            "  [bold bright_white]4[/bold bright_white] Storage breakdown    [bold bright_white]5[/bold bright_white] Running processes    [bold bright_white]6[/bold bright_white] Send notification\n"
            "  [bold bright_white]7[/bold bright_white] Read notifications   [bold bright_white]8[/bold bright_white] Bind ports           [bold bright_white]9[/bold bright_white] App logs\n"
            "  [bold bright_green]H[/bold bright_green] ❤️  [bold]Live Health Monitor[/bold]"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "1": _action_device_info_dashboard(dev_id)
        elif choice == "2": _action_battery_info(dev_id)
        elif choice == "3": _action_network_info(dev_id)
        elif choice == "4": _action_storage_info(dev_id)
        elif choice == "5": _action_running_processes(dev_id)
        elif choice == "6": _action_send_notification(dev_id)
        elif choice == "7": _action_read_notifications(dev_id)
        elif choice == "8":
            if APPS:
                app_key = Prompt.ask("App", choices=list(APPS.keys()))
                action_bind(app_key, key)
        elif choice == "9":
            if APPS:
                app_key = Prompt.ask("App", choices=list(APPS.keys()))
                action_logs(app_key, key)
        elif choice.upper() == "H": _action_health_monitor(dev_id)
        _wait_any_key()

def _device_config_menu(key):
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]⚙️  DEVICE CONFIG — {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_yellow", padding=(0, 1)))
        info = DEVICES[key]
        hist = ", ".join(str(p) for p in info.get("port_history", [])) or "—"
        console.print(f"  [dim]{info.get('model', '?')}  │  {info.get('ip', '')}:{info.get('port', '')}  │  history: {hist}[/dim]")
        console.print(
            "\n  [bold bright_green]e[/bold bright_green] ✏️  Edit device\n"
            "  [bold bright_yellow]g[/bold bright_yellow] ⏯  Toggle enable/disable\n"
            "  [bold bright_red]h[/bold bright_red] 🗑  Remove device\n"
            "  [bold bright_cyan]d[/bold bright_cyan] 🔄 Refresh info"
        )
        console.print("\n  [bold bright_red]b[/bold bright_red] ⬅ Back")
        choice = _ask_key("action")
        if choice == "b": return
        elif choice == "d": continue
        elif choice == "e":
            new_ip = Prompt.ask("IP", default=info.get("ip", ""))
            new_port = Prompt.ask("Port", default=str(info.get("port", "")))
            new_model = Prompt.ask("Model", default=info.get("model", ""))
            DEVICES[key] = {**info, "ip": new_ip, "port": new_port, "model": new_model}
            save_config(); console.print("[green]✅ Updated[/green]")
        elif choice == "g":
            DEVICES[key]["disabled"] = not DEVICES[key].get("disabled", False)
            save_config(); console.print(f"[green]✅ {'Disabled' if DEVICES[key].get('disabled') else 'Enabled'}[/green]")
        elif choice == "h":
            if Confirm.ask(f"[red]Remove '{key}'?[/red]"):
                del DEVICES[key]; save_config(); console.print("[green]✅ Removed[/green]"); return
        _wait_any_key()

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN DEVICE COMMAND CENTER
# ═══════════════════════════════════════════════════════════════════════════

def _device_summary(key):
    """One-line status for a device, from config only (cheap, safe to redraw)."""
    info = DEVICES.get(key, {})
    bits = [str(info.get("model") or "Android device")]
    if info.get("type") == "usb":
        if info.get("serial"):
            bits.append(str(info["serial"]))
    elif info.get("ip"):
        bits.append(f"{info.get('ip')}:{info.get('port', '')}")
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
    """Per-device Command Center: grouped categories first, expert keypad on demand."""
    if key not in DEVICES:
        return
    categories = [
        ("1", "🖥  Screen & input", _device_screen_menu),
        ("2", "📦  Apps", _device_apps_menu),
        ("3", "📁  Files", _device_files_menu),
        ("4", "🔧  Device control", _device_control_menu),
        ("5", "🔗  Dev tools", _device_devtools_menu),
        ("6", "⚙️   Configure device", _device_config_menu),
        ("e", "⌨️   Expert keypad — every action on one screen", _device_actions_expert),
    ]
    while True:
        choice = run_menu(
            key.upper(),
            [(k, label) for k, label, _ in categories],
            breadcrumb="dashboard › device",
            subtitle=_device_summary(key),
            accent="bright_cyan",
        )
        if choice is None:
            return
        if choice == "":
            continue
        for k, _, fn in categories:
            if choice == k:
                fn(key)
                break

def _device_actions_expert(key):
    while True:
        console.clear()
        _device_header(key)
        console.print()
        console.print(Panel(
            "[bold bright_cyan]1[/bold bright_cyan] Mirror    [bold bright_cyan]2[/bold bright_cyan] Screenshot   [bold bright_cyan]3[/bold bright_cyan] Record     [bold bright_cyan]4[/bold bright_cyan] Wake        [bold bright_cyan]5[/bold bright_cyan] Lock\n"
            "[bold bright_cyan]6[/bold bright_cyan] Type      [bold bright_cyan]7[/bold bright_cyan] Tap XY       [bold bright_cyan]8[/bold bright_cyan] Swipe      [bold bright_cyan]9[/bold bright_cyan] Keys\n"
            "[bold bright_cyan]A[/bold bright_cyan] Clip→dev [bold bright_cyan]B[/bold bright_cyan] Read clip     [bold bright_cyan]C[/bold bright_cyan] Open URL",
            title="[bold bright_cyan]🖥 SCREEN & INPUT[/bold bright_cyan]", box=box.ROUNDED, border_style="dim cyan", padding=(0, 1)))
        console.print(Panel(
            "[bold bright_green]D[/bold bright_green] Open app  [bold bright_green]E[/bold bright_green] List apps    [bold bright_green]F[/bold bright_green] Uninstall  [bold bright_green]G[/bold bright_green] Clear data  [bold bright_green]H[/bold bright_green] Force stop\n"
            "[bold bright_green]I[/bold bright_green] App info  [bold bright_green]J[/bold bright_green] Install APK  [bold bright_green]K[/bold bright_green] Nuke + relaunch",
            title="[bold bright_green]📦 APPS[/bold bright_green]", box=box.ROUNDED, border_style="dim green", padding=(0, 1)))
        console.print(Panel(
            "[bold bright_yellow]L[/bold bright_yellow] Push      [bold bright_yellow]M[/bold bright_yellow] Pull         [bold bright_yellow]N[/bold bright_yellow] Browse",
            title="[bold bright_yellow]📁 FILES[/bold bright_yellow]", box=box.ROUNDED, border_style="dim yellow", padding=(0, 1)))
        console.print(Panel(
            "[bold bright_magenta]O[/bold bright_magenta] Reboot    [bold bright_magenta]P[/bold bright_magenta] WiFi         [bold bright_magenta]Q[/bold bright_magenta] Data        [bold bright_magenta]R[/bold bright_magenta] BT          [bold bright_magenta]S[/bold bright_magenta] Volume\n"
            "[bold bright_magenta]T[/bold bright_magenta] Bright    [bold bright_magenta]U[/bold bright_magenta] Shell",
            title="[bold bright_magenta]🔧 CONTROL[/bold bright_magenta]", box=box.ROUNDED, border_style="dim magenta", padding=(0, 1)))
        console.print(Panel(
            "[bold bright_white]V[/bold bright_white] Info      [bold bright_white]W[/bold bright_white] Battery      [bold bright_white]X[/bold bright_white] Network     [bold bright_white]Y[/bold bright_white] Storage    [bold bright_white]Z[/bold bright_white] Processes\n"
            "[bold bright_white]0[/bold bright_white] Health    [bold bright_white]#[/bold bright_white] Notify       [bold bright_white]@[/bold bright_white] Bind        [bold bright_white]~[/bold bright_white] App logs",
            title="[bold bright_white]🔗 DEV TOOLS[/bold bright_white]", box=box.ROUNDED, border_style="dim white", padding=(0, 1)))
        console.print(
            "  [bold bright_green]e[/bold bright_green] Edit  [bold bright_yellow]g[/bold bright_yellow] Toggle  [bold bright_red]h[/bold bright_red] Remove  [bold bright_cyan]d[/bold bright_cyan] Refresh  [bold bright_red]b[/bold bright_red] ⬅ Back")
        console.print()
        c = Prompt.ask("[bold bright_white]▸[/bold bright_white] [dim]command[/dim]", default="b")
        if c == "b": return
        did = check_and_connect(key, interactive=True)
        # ── Screen & Input ───────────────────────────────────────
        if c == "1": action_mirror(key)
        elif c == "2": action_media(key, "screenshot")
        elif c == "3": action_media(key, "record")
        elif c == "4" and did: run_cmd(f"adb -s {did} shell input keyevent KEYCODE_WAKEUP"); console.print("[green]✅ Woken[/green]")
        elif c == "5" and did: run_cmd(f"adb -s {did} shell input keyevent KEYCODE_SLEEP"); console.print("[green]✅ Locked[/green]")
        elif c == "6" and did: _action_type_text(did)
        elif c == "7" and did: _action_tap_screen(did)
        elif c == "8" and did: _action_swipe(did)
        elif c == "9" and did: _action_key_combo(did)
        elif c.upper() == "A" and did: _action_clipboard_copy(did)
        elif c.upper() == "B" and did: _action_clipboard_read(did)
        elif c.upper() == "C" and did: _action_open_url(did)
        # ── Apps ─────────────────────────────────────────────────
        elif c.upper() == "D" and did and APPS:
            ak = Prompt.ask("App", choices=list(APPS.keys())); action_open(ak, key)
        elif c.upper() == "E" and did: _action_list_apps(did)
        elif c.upper() == "F" and did: _action_uninstall_app(did)
        elif c.upper() == "G" and did: _action_clear_app_data(did)
        elif c.upper() == "H" and did: _action_force_stop(did)
        elif c.upper() == "I" and did: _action_app_info(did)
        elif c.upper() == "J" and did: _action_install_apk_from_pc(did)
        elif c.upper() == "K" and did and APPS:
            ak = Prompt.ask("App", choices=list(APPS.keys())); action_nuke(ak, key)
        # ── Files ────────────────────────────────────────────────
        elif c.upper() == "L" and did: _action_push_file(did)
        elif c.upper() == "M" and did: _action_pull_file(did)
        elif c.upper() == "N" and did: _action_browse_storage(did)
        # ── Control ──────────────────────────────────────────────
        elif c.upper() == "O" and did: _action_reboot_menu(did)
        elif c.upper() == "P" and did: _action_toggle_wifi(did)
        elif c.upper() == "Q" and did: _action_toggle_data(did)
        elif c.upper() == "R" and did: _action_toggle_bluetooth(did)
        elif c.upper() == "S" and did: _action_volume_control(did)
        elif c.upper() == "T" and did: _action_brightness_control(did)
        elif c.upper() == "U" and did: _action_interactive_shell(did)
        # ── Dev Tools ────────────────────────────────────────────
        elif c.upper() == "V" and did: _action_device_info_dashboard(did)
        elif c.upper() == "W" and did: _action_battery_info(did)
        elif c.upper() == "X" and did: _action_network_info(did)
        elif c.upper() == "Y" and did: _action_storage_info(did)
        elif c.upper() == "Z" and did: _action_running_processes(did)
        elif c == "0" and did: _action_health_monitor(did)
        elif c == "#" and did:
            console.print("  [cyan]1[/cyan] Send notification  [cyan]2[/cyan] Read notifications")
            sub = Prompt.ask("Pick", default="1")
            if sub == "1": _action_send_notification(did)
            elif sub == "2": _action_read_notifications(did)
        elif c == "@" and did and APPS:
            ak = Prompt.ask("App", choices=list(APPS.keys())); action_bind(ak, key)
        elif c == "~" and did and APPS:
            ak = Prompt.ask("App", choices=list(APPS.keys())); action_logs(ak, key)
        # ── Config ───────────────────────────────────────────────
        elif c == "e":
            info = DEVICES[key]
            nip = Prompt.ask("IP", default=info.get("ip", ""))
            npt = Prompt.ask("Port", default=str(info.get("port", "")))
            nmd = Prompt.ask("Model", default=info.get("model", ""))
            DEVICES[key] = {**info, "ip": nip, "port": npt, "model": nmd}
            save_config(); console.print("[green]✅ Updated[/green]")
        elif c == "g":
            DEVICES[key]["disabled"] = not DEVICES[key].get("disabled", False)
            save_config(); console.print(f"[green]✅ {'Disabled' if DEVICES[key].get('disabled') else 'Enabled'}[/green]")
        elif c == "h":
            if Confirm.ask(f"[red]Remove '{key}'?[/red]"):
                del DEVICES[key]; save_config(); console.print("[green]✅ Removed[/green]"); return
        elif c == "d": continue
        _wait_any_key()

def app_actions(key):
    while True:
        console.clear()
        console.print(Panel(f"[bold bright_white]📦  {key.upper()}[/bold bright_white]", box=box.HEAVY, border_style="bright_green", padding=(0, 1)))
        data = APPS[key]
        pkg = data.get("package") or resolve_package(key) or "?"
        console.print(f"  [dim]{data.get('path', '')}  │  port {data.get('port', '')}  │  {pkg}[/dim]")
        console.print()
        console.print(
            "  [bold bright_green]1[/bold bright_green] 🚀 [dim]Run local (pick device)[/dim]"
        )
        console.print(
            "  [bold bright_green]2[/bold bright_green] 🚀 [dim]Run remote (pick device)[/dim]"
        )
        console.print(
            "  [bold bright_green]3[/bold bright_green] 🚀 [dim]Run on ALL online devices[/dim]"
        )
        console.print(
            "  [bold bright_green]4[/bold bright_green] 🚀 [dim]Open app on a device[/dim]"
        )
        console.print(
            "  [bold bright_green]5[/bold bright_green] 📦 [dim]Build release APK[/dim]"
        )
        console.print(
            "  [bold bright_green]6[/bold bright_green] 🧹 [dim]flutter clean + pub get[/dim]"
        )
        console.print(
            "  [bold bright_green]7[/bold bright_green] 🖥  [dim]Start backend[/dim]"
        )
        console.print()
        console.print("  [bold bright_red]b[/bold bright_red] ⬅  [dim]Back to dashboard[/dim]")
        choice = _ask_key("action")
        if choice == "b": return
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
    console.print(f"[dim]Aliases are live now — try `{name}-all`, `{name}-release`, or `fenox-mobile run {name} <device>`.[/dim]")

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
        console.print(f"\n[green]✅ Registered {len(added)} project(s). Aliases are live now — try `{first}-all` or `fenox-mobile run {first} <device>`.[/green]")


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
        console.print(f"[yellow]No running session '{session}'. Start it first with `fenox-mobile run {app_key} <device>` (or {app_key}-all).[/yellow]")
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
        console.print(f"[yellow]No release APK found for {app_key}. Build it first (`fenox-mobile build {app_key}`).[/yellow]")
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

def interactive_menu():
    """Live dashboard: keeps itself up to date while waiting for one keypress."""
    shortcuts = [
        ("d", "Doctor"), ("s", "Sync"), ("p", "Pair"), ("q", "Pair QR"),
        ("f", "Discover"), ("n", "Scan"), ("a", "Add app"),
        ("+", "Edit device"), ("-", "Delete device"), ("g", "Toggle device"),
        ("m", "Rename device"), ("b", "Bind all ports"), ("r", "Batch screenshot"),
        ("c", "Edit config"),
    ]
    handlers = {
        "d": action_doctor, "s": action_sync, "p": action_pair, "q": action_pair_qr,
        "f": action_discover, "n": action_scan, "a": lambda: action_add_app(),
        "b": lambda: action_bind("all", "all"),
        "r": lambda: action_media("all", "screenshot"),
        "+": action_edit_device, "-": action_delete_device,
        "g": action_toggle_device, "m": _rename_device_prompt,
        "c": _open_config_in_editor,
    }
    # The dashboard is re-rendered on every refresh, so the index maps are
    # captured here rather than passed around.
    indices = {}

    def body():
        renderable, dev_index, app_index = _build_dashboard()
        indices["dev"], indices["app"] = dev_index, app_index
        return Group(_banner(), renderable)

    while True:
        choice = run_menu(
            options=shortcuts,
            body=body,
            breadcrumb=f"fenox v{FENOX_VERSION} · live dashboard",
            subtitle="press a device # or app # to open it, or use a shortcut below",
            footer=("  [bold bright_red]x[/bold bright_red] [dim]quit[/dim]"
                    "    [dim]· single keypress, no Enter[/dim]"),
            interval=5.0,
            accent="bright_cyan",
            back_keys=("x", "esc"),
        )
        if choice is None:
            return
        if choice == "":
            continue
        if choice.isdigit():
            number = int(choice)
            if number in indices.get("dev", {}):
                device_actions(indices["dev"][number])
            elif number in indices.get("app", {}):
                app_actions(indices["app"][number])
            continue
        handler = handlers.get(choice)
        if handler:
            handler()
            _wait_any_key("press any key to return to the dashboard")

# --- Main Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="fenox-mobile")
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
    parser.add_argument("--version", action="version", version=f"fenox-mobile {FENOX_VERSION}")
    parser.add_argument("--generate-completions", metavar="SHELL", choices=["bash", "zsh"], help=argparse.SUPPRESS)

# --- Clean exits: no tracebacks on Ctrl+C or piped/EOF input -----------------
def _main():
    try:
        ensure_shared_adb_server()
        if (len(sys.argv) > 1 and sys.argv[1] not in ("--version", "-h", "--help", "--generate-completions")
                and sys.argv[1] not in KNOWN_COMMANDS):
            action_plugin(sys.argv[1], sys.argv[2:])
            return
        if "--generate-completions" in sys.argv:
            idx = sys.argv.index("--generate-completions")
            shell = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "bash"
            generate_completions(shell)
            return
        if len(sys.argv) == 1:
            interactive_menu()
        else:
            args = parser.parse_args()
            _dispatch(args)
    except KeyboardInterrupt:
        console.print("\n[cyan]👋 Interrupted.[/cyan]")
        sys.exit(130)
    except EOFError:
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

# --- Run ----------------------------------------------------------------------
if __name__ == "__main__":
    if "--generate-aliases" in sys.argv:
        generate_aliases()
    else:
        _main()

