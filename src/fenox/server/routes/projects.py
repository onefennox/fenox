"""Flutter project registry."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ...core import flutter, projects
from ..security import require_owner

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(require_owner)])


class ProjectCreate(BaseModel):
    # Optional: an omitted or blank name is derived from the folder, so picking a
    # directory in the browser is enough to register a project.
    name: str = ""
    path: str
    port: str | None = None
    api_local: str | None = None
    api_remote: str | None = None
    socket_local: str | None = None
    socket_remote: str | None = None
    additional_ports: list[str] | str | None = None
    backend_path: str | None = None
    backend_cmd: str | None = None
    update: bool = False


class ProjectUpdate(BaseModel):
    path: str | None = None
    port: str | None = None
    api_local: str | None = None
    api_remote: str | None = None
    socket_local: str | None = None
    socket_remote: str | None = None
    additional_ports: list[str] | str | None = None
    backend_path: str | None = None
    backend_cmd: str | None = None


class ScanRequest(BaseModel):
    path: str | None = None


@router.get("")
def list_projects(request: Request) -> dict:
    return {"projects": request.app.state.store.projects()}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(request: Request, body: ProjectCreate) -> dict:
    store = request.app.state.store
    name = projects.sanitize_name(body.name) or projects.suggest_name(body.path, set(store.projects()))
    if not name:
        raise HTTPException(status_code=422, detail="invalid project name")
    existing = store.project(name)
    if existing and not body.update:
        raise HTTPException(status_code=409, detail="a project with that name already exists")

    entry = projects.build_entry(
        name,
        body.path,
        store.settings,
        port=body.port,
        api_local=body.api_local,
        api_remote=body.api_remote,
        socket_local=body.socket_local,
        socket_remote=body.socket_remote,
        additional_ports=body.additional_ports,
        backend_path=body.backend_path,
        backend_cmd=body.backend_cmd,
    )
    if existing:
        merged = {**existing, **{key: value for key, value in entry.items() if value}}
        entry = merged
    store.upsert_project(name, entry)
    return {"id": name, "project": entry}


@router.get("/{project_id}")
def get_project(request: Request, project_id: str) -> dict:
    entry = request.app.state.store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {"id": project_id, "project": entry}


@router.patch("/{project_id}")
def update_project(request: Request, project_id: str, body: ProjectUpdate) -> dict:
    store = request.app.state.store
    entry = store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    changes = body.model_dump(exclude_none=True)
    if "path" in changes:
        changes["path"] = str(Path(str(changes["path"])).expanduser())
    if isinstance(changes.get("additional_ports"), str):
        changes["additional_ports"] = [p.strip() for p in changes["additional_ports"].split(",") if p.strip()]
    if body.backend_path or body.backend_cmd:
        backend = dict(entry.get("backend") or {})
        if body.backend_path:
            backend["path"] = body.backend_path
        if body.backend_cmd:
            backend["cmd"] = body.backend_cmd
        changes["backend"] = backend
    changes.pop("backend_path", None)
    changes.pop("backend_cmd", None)
    entry.update(changes)
    if body.path:
        package = projects.detect_package(entry["path"])
        if package:
            entry["package"] = package
    store.upsert_project(project_id, entry)
    return {"id": project_id, "project": entry}


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(request: Request, project_id: str) -> Response:
    store = request.app.state.store
    if store.project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    store.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/scan")
def scan_projects(request: Request, body: ScanRequest | None = None) -> dict:
    store = request.app.state.store
    base = (body.path if body and body.path else None) or store.settings.get("projects_dir")
    if not base:
        raise HTTPException(status_code=422, detail="no projects directory configured")
    found = projects.scan(store, base)
    return {"added": [name for name, _ in found], "projects": store.projects()}


class QualityRequest(BaseModel):
    action: str


@router.get("/{project_id}/quality")
def quality_actions(project_id: str) -> dict:
    """The checks available for a project.

    `project_id` is not used — the catalogue is global — but it stays in the path
    so this cannot be shadowed by `/{project_id}`, which is registered above it.
    """
    return {
        "actions": [
            {"id": key, "label": spec["label"], "hint": spec["hint"]}
            for key, spec in flutter.QUALITY_ACTIONS.items()
        ]
    }


@router.post("/{project_id}/quality")
async def run_quality(request: Request, project_id: str, body: QualityRequest) -> dict:
    """Run one check and return its output.

    Executed off the event loop: `flutter test` can take minutes, and blocking
    the loop would freeze every other request including the device streams.
    """
    store = request.app.state.store
    entry = store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    if body.action not in flutter.QUALITY_ACTIONS:
        raise HTTPException(status_code=422, detail=f"unknown action: {body.action}")

    binary = flutter.resolve(store.settings.get("flutter_path"), entry.get("path"))
    if not binary:
        raise HTTPException(status_code=409, detail="the flutter SDK was not found; set it in Settings")

    started = time.time()
    ok, output = await run_in_threadpool(flutter.run_action, binary, entry, body.action)
    return {"action": body.action, "ok": ok, "output": output, "seconds": round(time.time() - started, 1)}


@router.get("/{project_id}/tree")
def project_tree(request: Request, project_id: str, path: str = "") -> dict:
    """One directory of the project's own files.

    Confined to the project: `resolve_within` compares resolved paths, so a
    request cannot walk out with `..` or through a symlink.
    """
    entry = request.app.state.store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    entries, error = projects.list_tree(entry, path)
    if error:
        raise HTTPException(status_code=400, detail=error)
    root = projects.project_root(entry)
    parent = str(Path(path).parent) if path and path != "." else ""
    return {"path": path, "parent": parent, "root": str(root) if root else "", "entries": entries}


@router.get("/{project_id}/file")
def project_file(request: Request, project_id: str, path: str) -> dict:
    """The contents of one text file, for reading in the browser."""
    entry = request.app.state.store.project(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="project not found")
    text, error = projects.read_text_file(entry, path)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"path": path, "text": text}
