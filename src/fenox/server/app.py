"""The Fenox hub application factory.

One process serves the REST API, the WebSocket endpoints and the built
single-page app. The factory takes an explicit data directory so tests can run
against a temporary store without touching the owner's installation.
"""
from __future__ import annotations

import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..core import adb, devices, mediamtx
from ..core.auth import AuthStore
from ..core.config import Store
from ..core.sessions import SessionManager
from ..version import __version__
from . import ws as ws_routes
from .routes import auth as auth_routes
from .routes import devices as device_routes
from .routes import files as file_routes
from .routes import mirror as mirror_routes
from .routes import phone as phone_routes
from .routes import projects as project_routes
from .routes import runs as run_routes
from .routes import settings as settings_routes
from .routes import system as system_routes
from .routes import toolbox as toolbox_routes


def _bundled_web_dir() -> Path | None:
    """The built SPA: packaged data first, then a source checkout."""
    packaged = Path(__file__).resolve().parent.parent / "web"
    if (packaged / "index.html").exists():
        return packaged
    repo_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if (repo_dist / "index.html").exists():
        return repo_dist
    return None


def create_app(data_dir: Path | str | None = None, store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store(data_dir).load()
        app.state.auth = AuthStore(app.state.store.paths.auth)
        settings = app.state.store.settings
        if settings.get("adb_path"):
            os.environ["FENOX_ADB_PATH"] = str(settings["adb_path"])
        if settings.get("adb_port"):
            os.environ["FENOX_ADB_PORT"] = str(settings["adb_port"])
        if os.environ.get("FENOX_NO_AUTODETECT"):
            # Tests: pin the port without probing the host.
            adb.configure_environment(int(settings.get("adb_port") or adb.DEFAULT_SERVER_PORT))
        else:
            adb.configure_environment()
            try:
                adb.ensure_server(force=True)
            except Exception:
                pass
        app.state.sessions = SessionManager(app.state.store)
        app.state.mirrors = {}
        app.state.mediamtx = mediamtx.MediaMTX(app.state.store.paths.data)
        app.state.serving = {
            "reach": app.state.store.settings.get("reach"),
            "port": app.state.store.settings.get("port"),
        }
        app.state.watcher = devices.DeviceWatcher(app.state.store).start()
        try:
            yield
        finally:
            app.state.watcher.stop()
            app.state.sessions.shutdown()
            for session in list(app.state.mirrors.values()):
                session.stop()
            app.state.mediamtx.stop()

    app = FastAPI(
        title="Fenox",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(auth_routes.router)
    app.include_router(system_routes.router)
    app.include_router(device_routes.router)
    app.include_router(project_routes.router)
    app.include_router(run_routes.router)
    app.include_router(toolbox_routes.router)
    app.include_router(phone_routes.router)
    app.include_router(file_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(mirror_routes.router)
    app.include_router(ws_routes.router)

    web_dir = _bundled_web_dir()
    if web_dir is not None:
        mimetypes.add_type("application/manifest+json", ".webmanifest")
        mimetypes.add_type("text/javascript", ".js")

        assets = web_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        index = web_dir / "index.html"
        root = web_dir.resolve()

        @app.get("/", include_in_schema=False)
        async def index_page() -> FileResponse:
            return FileResponse(index)

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(request: Request, path: str):
            # API paths never fall through to the SPA.
            if path == "api" or path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            # Serve a real file when one exists (favicon, service worker, manifest);
            # otherwise hand back the app shell so client-side routes work.
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
