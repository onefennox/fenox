"""Access control for the hub.

One owner guards everything behind `/api` except setup, auth and static assets.
The owner proves themselves with either the session cookie (the browser) or the
bearer token (scripts and the CLI).
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from ..core.auth import AuthStore

COOKIE_NAME = "fenox_session"


def auth_store(request: Request) -> AuthStore:
    return request.app.state.auth


def is_authenticated(request: Request) -> bool:
    auth: AuthStore = request.app.state.auth
    if not auth.has_owner():
        return False
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and auth.verify_session(cookie):
        return True
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return auth.verify_token(header[7:].strip())
    return False


async def require_owner(request: Request) -> None:
    """FastAPI dependency: 401 unless the owner is authenticated."""
    if not request.app.state.auth.has_owner():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="setup required",
            headers={"X-Fenox-Setup": "required"},
        )
    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")


def set_session_cookie(response, token: str, *, remember: bool) -> None:
    max_age = 60 * 60 * 24 * 30 if remember else 60 * 60 * 12
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,   # localhost by default; TLS terminates in front when exposed
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
