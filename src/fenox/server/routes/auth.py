"""First-run setup and owner login.

Setup is available only while no owner exists; once it has run there is no route
that creates a credential, by design.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..security import auth_store, clear_session_cookie, is_authenticated, set_session_cookie

router = APIRouter(prefix="/api", tags=["auth"])


class SetupRequest(BaseModel):
    password: str = Field(min_length=6, max_length=256)


class LoginRequest(BaseModel):
    password: str
    remember: bool = False


@router.get("/setup")
def setup_status(request: Request) -> dict:
    return {"configured": auth_store(request).has_owner()}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(request: Request, response: Response, body: SetupRequest) -> dict:
    auth = auth_store(request)
    if auth.has_owner():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="owner already configured")
    auth.set_owner(body.password)
    set_session_cookie(response, auth.issue_session(remember=True), remember=True)
    return {"configured": True}


@router.post("/auth/login")
def login(request: Request, response: Response, body: LoginRequest) -> dict:
    auth = auth_store(request)
    if not auth.has_owner():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="setup required")
    if not auth.verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")
    set_session_cookie(response, auth.issue_session(remember=body.remember), remember=body.remember)
    return {"authenticated": True}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"authenticated": False}


@router.get("/auth/me")
def me(request: Request) -> dict:
    auth = auth_store(request)
    return {
        "configured": auth.has_owner(),
        "authenticated": is_authenticated(request),
    }
