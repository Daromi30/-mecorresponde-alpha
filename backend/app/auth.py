from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import User, UserSession
from .config import settings
from .db import get_db

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
SESSION_COOKIE = "mcr_session"
SESSION_DAYS = 30


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
        dklen=32,
    )
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_raw, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def issue_session(db: Session, user: User, response: Response) -> UserSession:
    token = secrets.token_urlsafe(32)
    expires_at = now() + timedelta(days=SESSION_DAYS)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=expires_at,
    )
    db.add(session)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.render,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return session


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=settings.render,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def get_session_from_request(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    token_hash = hash_session_token(token)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if not session or session.revoked_at is not None:
        return None
    if _as_utc(session.expires_at) <= now():
        return None
    return session


def get_user_from_request(request: Request, db: Session) -> User | None:
    session = get_session_from_request(request, db)
    if not session:
        return None
    user = db.get(User, session.user_id)
    if not user or user.disabled_at is not None:
        return None
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    return get_user_from_request(request, db)


def require_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    user = get_user_from_request(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
