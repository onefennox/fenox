"""Flutter project registry and detection.

A project entry records what a launch needs: the project directory, the backend
port and API URLs, optional websocket URLs, additional reverse ports, and the
Android package name. Detection is best-effort and never blocks registration:
the owner can always correct a field.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SKIP_DIRS = {"build", "node_modules", "windows", "linux", "macos", "web", "example", ".git", ".dart_tool"}


def sanitize_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", str(raw or "").strip().lower()).strip("-_")


def repo_root(path: str) -> str | None:
    current = os.path.abspath(os.path.expanduser(path))
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def detect_package(project_path: str) -> str | None:
    """The Android application id, from Gradle, else the pubspec name."""
    root = Path(os.path.expanduser(project_path))
    for candidate in ("android/app/build.gradle.kts", "android/app/build.gradle"):
        gradle = root / candidate
        if not gradle.exists():
            continue
        try:
            content = gradle.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = re.search(r'applicationId\s*=?\s*["\']([\w.]+)["\']', content)
        if match:
            return match.group(1)
        match = re.search(r'namespace\s*=?\s*["\']([\w.]+)["\']', content)
        if match:
            return f"{match.group(1)}.MainActivity".rsplit(".MainActivity", 1)[0]
    pubspec = root / "pubspec.yaml"
    if pubspec.exists():
        try:
            match = re.search(r'^\s*name:\s*([\w-]+)', pubspec.read_text(encoding="utf-8", errors="ignore"), re.M)
        except OSError:
            match = None
        if match:
            return match.group(1)
    return None


def find_backend_dir(name: str, project_path: str) -> str | None:
    """A sibling `<name>_backend` or a common backend directory inside the repo."""
    project = os.path.abspath(os.path.expanduser(project_path))
    repo = repo_root(project) or project
    base = os.path.dirname(repo)
    candidates = [os.path.join(base, rel) for rel in
                  (f"{name}_backend", f"{name}-backend", f"{name}_server", f"{name}-server", f"{name}_api", f"{name}-api")]
    candidates += [os.path.join(repo, rel) for rel in
                   ("backend", "server", "api", "apps/server", "apps/api", "apps/backend", "services/api", "services/server")]
    markers = ("package.json", "requirements.txt", "manage.py", "app.py", "server.py", "pyproject.toml", "go.mod", "Cargo.toml")
    seen: set[str] = set()
    for candidate in candidates:
        candidate = os.path.abspath(os.path.expanduser(candidate))
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isdir(candidate) and any(os.path.exists(os.path.join(candidate, marker)) for marker in markers):
            return candidate
    return None


def detect_port(backend_path: str | None) -> str | None:
    """Sniff the port a backend listens on: env file, then npm scripts, then Python."""
    if not backend_path:
        return None
    path = Path(os.path.expanduser(backend_path))
    if not path.is_dir():
        return None
    for env_file in (".env", ".env.local", ".env.development", ".env.production"):
        candidate = path / env_file
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                    match = re.match(r'^\s*PORT\s*[=:]\s*["\']?(\d{2,5})', line, re.I)
                    if match:
                        return match.group(1)
            except OSError:
                pass
    package = path / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8", errors="ignore")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        for key in ("dev", "start", "serve"):
            script = scripts.get(key, "")
            match = re.search(r'(?:--port|-p)\s+("\d{2,5}"|\d{2,5})', script) or re.search(r'--port\s+(\d{2,5})', script)
            if match:
                return match.group(1).strip('"')
    for name in ("app.py", "server.py", "main.py", "manage.py"):
        candidate = path / name
        if candidate.exists():
            try:
                match = re.search(r'(?:port|PORT)\s*[=:]\s*["\']?(\d{2,5})', candidate.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                match = None
            if match:
                return match.group(1)
    return None


def guess_backend_cmd(backend_path: str | None) -> str | None:
    if not backend_path:
        return None
    path = Path(os.path.expanduser(backend_path))
    package = path / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8", errors="ignore")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        for key, command in (("dev", "npm run dev"), ("start", "npm start"), ("serve", "npm run serve")):
            if scripts.get(key):
                return command
    for name in ("manage.py", "app.py", "server.py", "main.py"):
        if (path / name).exists():
            return f"python {name}"
    if (path / "go.mod").exists():
        return "go run ."
    if (path / "Cargo.toml").exists():
        return "cargo run"
    return None


def guess_remote(settings: dict, name: str) -> str:
    domain = str(settings.get("remote_domain") or "").strip()
    if not domain or domain == "example.com":
        return ""
    return f"https://{name}.{domain}/api"


def build_entry(name: str, path: str, settings: dict, **overrides) -> dict:
    """Assemble a project entry, detecting whatever was not provided."""
    path = os.path.abspath(os.path.expanduser(path))
    backend_dir = overrides.get("backend_path") or find_backend_dir(name, path)
    port = overrides.get("port") or detect_port(backend_dir) or "8080"
    port = str(port)
    entry: dict = {
        "path": path,
        "port": port,
        "api_local": overrides.get("api_local") or f"http://localhost:{port}/api",
    }
    remote = overrides.get("api_remote")
    if remote is None:
        remote = guess_remote(settings, name)
    if remote:
        entry["api_remote"] = remote
    for key in ("socket_local", "socket_remote"):
        if overrides.get(key):
            entry[key] = overrides[key]
    additional = overrides.get("additional_ports")
    if additional:
        if isinstance(additional, str):
            additional = [p.strip() for p in additional.split(",") if p.strip()]
        entry["additional_ports"] = additional
    if backend_dir and os.path.isdir(backend_dir):
        command = overrides.get("backend_cmd") or guess_backend_cmd(backend_dir)
        if command:
            entry["backend"] = {"path": backend_dir, "cmd": command}
    package = overrides.get("package") or detect_package(path)
    if package:
        entry["package"] = package
    return entry


def iter_flutter_projects(base: str, max_depth: int = 3):
    base = os.path.abspath(os.path.expanduser(base))
    if not os.path.isdir(base):
        return
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        if root[len(base):].count(os.sep) > max_depth:
            dirs[:] = []
            continue
        if "pubspec.yaml" in files and os.path.isdir(os.path.join(root, "android")):
            yield root


def suggest_name(path: str, existing: set[str] | None = None) -> str:
    """A free, human name for the project at `path`.

    Same preference as `name_for_project` — a generic folder like `mobile-app`
    inside a repo is named after the repo — but never returns a name that is
    already taken, so registration can derive the name from the folder alone.
    """
    taken = existing or set()
    name = name_for_project(path, set()) or sanitize_name(os.path.basename(os.path.abspath(path)))
    if not name:
        name = "project"
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name}{n}", n + 1
    return candidate


def name_for_project(path: str, existing: set[str]) -> str | None:
    repo = repo_root(path)
    base_dir = os.path.basename(path)
    generic = re.match(r"^(mobile|app|client|frontend|apps|ui|flutter)([-_]?(app|mobile|client|frontend|ui))?$", base_dir.lower())
    if repo and os.path.realpath(repo) != os.path.realpath(path) and generic:
        name = sanitize_name(os.path.basename(repo))
    else:
        name = sanitize_name(base_dir)
    if not name or name in existing:
        return None
    return name


def scan(store, base: str) -> list[tuple[str, dict]]:
    """Register every new Flutter project under `base`. Returns (name, entry)."""
    existing = {os.path.realpath(os.path.expanduser(entry.get("path", ""))).rstrip("/") for entry in store.projects().values()}
    found: list[tuple[str, dict]] = []
    reserved = set(store.projects())
    for project_path in sorted(iter_flutter_projects(base)):
        if os.path.realpath(project_path).rstrip("/") in existing:
            continue
        name = name_for_project(project_path, reserved)
        if not name:
            continue
        entry = build_entry(name, project_path, store.settings)
        store.upsert_project(name, entry)
        reserved.add(name)
        found.append((name, entry))
    return found
