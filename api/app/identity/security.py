"""Credentials, tokens, and cookies (P1-T02, D-19).

Three rules this module exists to keep:

- Passwords are **Argon2id** hashes, never reversible, never logged.
- Tokens are opaque where they touch the database. A refresh token is a random
  string; only its SHA-256 digest is stored, so a database dump cannot be
  replayed.
- The access token is a short-lived signed JWT. It carries no secrets, only
  ids, the role and the school, so a request never needs a database round trip
  just to learn who is asking. It is still checked against the session row when
  the session must be revocable immediately (logout, rotation).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from app.core.config import Settings
from app.core.errors import UnauthorizedError
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Response

ACCESS_COOKIE = "stem_access"
REFRESH_COOKIE = "stem_refresh"

_pwd = PasswordHasher()


def hash_secret(raw: str) -> str:
    """Hash a PIN or any other short secret with Argon2id."""
    return _pwd.hash(raw)


def verify_secret(secret_hash: str | None, raw: str) -> bool:
    """Constant-ish answer for unknown users: a missing hash still costs a hash.

    Without this, an attacker can tell a real account from a fake one by
    response time alone. A 4-digit PIN makes that timing difference far more
    useful than it would be for a password.
    """
    if not secret_hash:
        _dummy_verify(raw)
        return False
    try:
        return _pwd.verify(secret_hash, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _pwd.hash("not-a-real-password")


def _dummy_verify(raw: str) -> None:
    try:
        _pwd.verify(_dummy_hash(), raw)
    except (VerifyMismatchError, InvalidHashError):
        pass


def secret_needs_rehash(secret_hash: str) -> bool:
    return _pwd.check_needs_rehash(secret_hash)


CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{1,15}$"
PIN_PATTERN = r"^\d{4,6}$"


def normalize_code(raw: str) -> str:
    """Codes are stored and compared uppercase.

    A child typing their code in lower case, or with stray spaces from a
    copy-paste, must not be told they are wrong.
    """
    return raw.strip().upper()


def new_refresh_token() -> str:
    """Opaque bearer for the refresh cookie. 384 bits of entropy."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Stored form of a refresh token. Deterministic, so lookup is an index hit."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    school_id: uuid.UUID


def create_access_token(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    role: str,
    school_id: uuid.UUID,
    settings: Settings,
    now: dt.datetime | None = None,
) -> str:
    issued = now or dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "sch": str(school_id),
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + dt.timedelta(seconds=settings.access_token_ttl_s)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    """Decode and validate. Any problem is a generic 401, never a reason string."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "sid"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Please sign in again.") from exc

    if payload.get("typ") != "access":
        raise UnauthorizedError("Please sign in again.")

    try:
        return AccessClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            session_id=uuid.UUID(str(payload["sid"])),
            role=str(payload.get("role", "")),
            school_id=uuid.UUID(str(payload["sch"])),
        )
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Please sign in again.") from exc


def set_session_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings,
) -> None:
    common: dict[str, Any] = {
        "httponly": True,
        "secure": settings.use_secure_cookies,
        "samesite": "lax",
        "path": "/",
        "domain": settings.cookie_domain,
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_ttl_s,
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_s,
        **common,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.use_secure_cookies,
            httponly=True,
            samesite="lax",
        )
