"""Individual backoffice sessions, intentionally separate from claimant accounts."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .auth_models import Reviewer, ReviewerSession
from .auth_throttle import AuthThrottle
from .config import settings


COOKIE = "mcr_reviewer_session"
SESSION_HOURS = 12
MAX_ACTIVE_SESSIONS = 3
ROLES = frozenset({"reviewer", "operator"})
LOGIN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,119}\Z")
login_throttle = AuthThrottle(
    5, 15 * 60, key_prefix="backoffice-login",
    detail="Too many login attempts. Try again later.",
)
# Consume the same PBKDF2 work for an unknown/disabled identifier.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_login(value: str) -> str:
    normalized = value.strip().casefold()
    if not LOGIN_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid login identifier")
    return normalized


def validate_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must contain 12 to 128 characters")
    return password


def create_reviewer(db: Session, login_id: str, password: str, role: str) -> Reviewer:
    normalized = normalize_login(login_id)
    validate_password(password)
    if role not in ROLES:
        raise ValueError("Invalid reviewer role")
    reviewer = Reviewer(login_id=normalized, password_hash=hash_password(password), role=role)
    db.add(reviewer)
    db.flush()
    return reviewer


def authenticate(db: Session, login_id: str, password: str) -> Reviewer | None:
    normalized = login_id.strip().casefold()
    login_throttle.check(db, normalized)
    reviewer = db.scalar(select(Reviewer).where(Reviewer.login_id == normalized))
    encoded = reviewer.password_hash if reviewer and reviewer.disabled_at is None else _DUMMY_HASH
    valid = verify_password(password, encoded)
    if not reviewer or reviewer.disabled_at is not None or not valid:
        login_throttle.hit(db, normalized)
        return None
    login_throttle.success(db, normalized)
    return reviewer


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db: Session, reviewer: Reviewer, response: Response) -> ReviewerSession:
    moment = utcnow()
    active = db.scalars(
        select(ReviewerSession)
        .where(ReviewerSession.reviewer_id == reviewer.id, ReviewerSession.revoked_at.is_(None))
        .order_by(ReviewerSession.created_at.desc(), ReviewerSession.id.desc())
    ).all()
    live = [item for item in active if as_utc(item.expires_at) > moment]
    for item in live[MAX_ACTIVE_SESSIONS - 1:]:
        item.revoked_at = moment
    token = secrets.token_urlsafe(32)
    session = ReviewerSession(
        reviewer_id=reviewer.id, token_digest=_digest(token),
        expires_at=moment + timedelta(hours=SESSION_HOURS),
    )
    db.add(session)
    db.flush()
    response.set_cookie(
        key=COOKIE, value=token, max_age=SESSION_HOURS * 3600,
        httponly=True, secure=settings.render, samesite="strict", path="/api",
    )
    response.headers["Cache-Control"] = "no-store"
    return session


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE, path="/api", httponly=True,
        secure=settings.render, samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def session_from_request(request: Request, db: Session) -> tuple[Reviewer, ReviewerSession] | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    session = db.scalar(select(ReviewerSession).where(ReviewerSession.token_digest == _digest(token)))
    if session is None or session.revoked_at is not None or as_utc(session.expires_at) <= utcnow():
        return None
    reviewer = db.get(Reviewer, session.reviewer_id)
    if reviewer is None or reviewer.disabled_at is not None or reviewer.role not in ROLES:
        return None
    return reviewer, session


def require_session(request: Request, db: Session) -> tuple[Reviewer, ReviewerSession]:
    resolved = session_from_request(request, db)
    if resolved is None:
        raise HTTPException(401, "Backoffice session required")
    return resolved


def revoke_sessions(db: Session, reviewer_id: str) -> int:
    moment = utcnow()
    rows = db.scalars(select(ReviewerSession).where(
        ReviewerSession.reviewer_id == reviewer_id,
        ReviewerSession.revoked_at.is_(None),
    )).all()
    for row in rows:
        row.revoked_at = moment
    return len(rows)
