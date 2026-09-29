"""Building artifacts and downloading them.

A build produces a file, so the interesting parts here are starting one, watching
it, and getting the file out. Artifacts are served by an explicit download route
rather than from the data directory on the web server, so the path can never be
used to reach anything else on disk: the build id is looked up, and only the file
that build recorded is ever returned.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...core import builds, devices, toolbox
from ..security import require_owner

router = APIRouter(tags=["builds"], dependencies=[Depends(require_owner)])


def _manager(request: Request) -> builds.BuildManager:
    return request.app.state.builds


class BuildRequest(BaseModel):
    kind: str


@router.get("/api/builds")
def list_builds(request: Request, project: str | None = None) -> dict:
    """Every build, newest first, optionally for one project."""
    rows = _manager(request).listing(project)
    return {
        "builds": rows,
        "kinds": [
            {"id": key, "label": spec["label"], "hint": spec["hint"]}
            for key, spec in builds.KINDS.items()
        ],
    }


@router.post("/api/projects/{project_id}/builds", status_code=201)
def start_build(request: Request, project_id: str, body: BuildRequest) -> dict:
    """Queue one build. It runs in the background; watch it on the socket."""
    store = request.app.state.store
    entry = store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        build = _manager(request).start(project_id, body.kind, entry, store.settings)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        # A preflight problem — flutter missing, the directory gone — is the
        # owner's to fix, so say so plainly instead of a 500.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return build.as_dict()


@router.get("/api/builds/{build_id}")
def get_build(request: Request, build_id: str) -> dict:
    row = _manager(request).row(build_id)
    if row is None:
        raise HTTPException(status_code=404, detail="build not found")
    return row


@router.get("/api/builds/{build_id}/log")
def build_log(request: Request, build_id: str) -> dict:
    manager = _manager(request)
    live = manager.get(build_id)
    if live is not None:
        return {"lines": live.transcript(), "live": True}
    log_path = manager.root / build_id / "build.log"
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail="no log for that build")
    return {"lines": log_path.read_text(errors="replace").splitlines(), "live": False}


@router.get("/api/builds/{build_id}/artifact")
def download_artifact(request: Request, build_id: str) -> FileResponse:
    """Serve the built file, using the name Flutter gave it."""
    manager = _manager(request)
    row = manager.row(build_id)
    if row is None:
        raise HTTPException(status_code=404, detail="build not found")
    path = manager.artifact(build_id)
    if path is None:
        raise HTTPException(status_code=404, detail="that build has no artifact to download")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=row.get("artifact_name") or path.name,
    )


@router.post("/api/builds/{build_id}/cancel")
def cancel_build(request: Request, build_id: str) -> dict:
    build = _manager(request).get(build_id)
    if build is None:
        raise HTTPException(status_code=409, detail="that build is no longer running")
    return {"cancelled": build.cancel()}


@router.delete("/api/builds/{build_id}", status_code=204)
def delete_build(request: Request, build_id: str) -> None:
    if not _manager(request).remove(build_id):
        raise HTTPException(status_code=404, detail="build not found")


class InstallRequest(BaseModel):
    device: str


@router.post("/api/builds/{build_id}/install")
def install_build(request: Request, build_id: str, body: InstallRequest) -> dict:
    """Push a built artifact to a device.

    This is the join between the two halves of the product: a build produces a
    file, a device can accept one, and until now nothing connected them. The
    file is already on this machine, so the usual `adb install` path applies
    unchanged.
    """
    manager = _manager(request)
    store = request.app.state.store

    row = manager.row(build_id)
    if row is None:
        raise HTTPException(status_code=404, detail="build not found")
    if row.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="that build has not finished successfully")

    spec = builds.KINDS.get(row.get("kind", "")) or {}
    if not spec.get("installable"):
        # An AAB is a Play Store upload. Saying so is better than letting adb
        # reject it with something about an archive.
        raise HTTPException(
            status_code=409,
            detail="a release AAB cannot be installed directly — upload it to Play, or build an APK to sideload",
        )

    path = manager.artifact(build_id)
    if path is None:
        raise HTTPException(status_code=404, detail="that build has no artifact to install")

    entry = store.device(body.device)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown device")

    serial = devices.resolve_serial(store, body.device)
    if serial is None:
        raise HTTPException(status_code=409, detail=f"device '{body.device}' is not connected")

    ok, detail = toolbox.install_apk(serial, str(path))
    if not ok:
        raise HTTPException(status_code=502, detail=detail or "the device refused the install")
    return {"ok": True, "device": body.device, "serial": serial, "artifact": row.get("artifact_name"), "detail": detail}
