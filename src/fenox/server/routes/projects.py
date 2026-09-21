"""Flutter project registry."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from ...core import projects
from ..security import require_owner

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(require_owner)])


class ProjectCreate(BaseModel):
    name: str
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
    name = projects.sanitize_name(body.name)
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
