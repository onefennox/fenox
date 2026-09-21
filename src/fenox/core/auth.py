"""Single-owner authentication.

There is one owner and one credential. No registration, no user list, no roles.
The owner sets a password on first run; after that a login hands out a signed
session cookie. A long-lived bearer token exists for scripts and the CLI.

Recovery is deliberately local-only: `fenox auth reset` (or `AuthStore.reset()`)
deletes the credential. There is never a network-reachable reset path.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_MAX_AGE = 60 * 60 * 12          # 12 hours
SESSION_MAX_AGE_REMEMBER = 60 * 60 * 24 * 30   # 30 days


class AuthStore:
    """Owner credential, session signing secret, and script token."""

    def __init__(self, path: Path):
        self.path = path
        self._hasher = PasswordHasher()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- owner credential --------------------------------------------------
    def has_owner(self) -> bool:
        return bool(self._data.get("password_hash"))

    def set_owner(self, password: str) -> None:
        if not password:
            raise ValueError("password must not be empty")
        self._data["password_hash"] = self._hasher.hash(password)
        self._data.setdefault("secret_key", secrets.token_urlsafe(32))
        self._data.setdefault("token", secrets.token_urlsafe(32))
        self._data["created_at"] = int(time.time())
        self._save()

    def verify_password(self, password: str) -> bool:
        stored = self._data.get("password_hash")
        if not stored:
            return False
        try:
            return self._hasher.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # -- sessions ----------------------------------------------------------
    @property
    def _serializer(self) -> URLSafeTimedSerializer:
        secret = self._data.get("secret_key")
        if not secret:
            raise RuntimeError("owner is not configured")
        return URLSafeTimedSerializer(secret, salt="fenox-session")

    def issue_session(self, remember: bool = False) -> str:
        return self._serializer.dumps({"sub": "owner", "remember": bool(remember)})

    def verify_session(self, token: str) -> bool:
        if not token:
            return False
        try:
            data = self._serializer.loads(token, max_age=SESSION_MAX_AGE_REMEMBER)
        except (BadSignature, SignatureExpired):
            return False
        max_age = SESSION_MAX_AGE_REMEMBER if data.get("remember") else SESSION_MAX_AGE
        issued = data.get("iat")
        if issued is not None and time.time() - float(issued) > max_age:
            return False
        return data.get("sub") == "owner"

    # -- script token ------------------------------------------------------
    def token(self) -> str | None:
        return self._data.get("token")

    def rotate_token(self) -> str:
        self._data["token"] = secrets.token_urlsafe(32)
        self._save()
        return self._data["token"]

    def verify_token(self, candidate: str | None) -> bool:
        expected = self._data.get("token")
        return bool(expected and candidate and hmac.compare_digest(expected, candidate))

    # -- recovery ----------------------------------------------------------
    def reset(self) -> None:
        """Remove the owner credential. Local recovery only."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._data = {}
