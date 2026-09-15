from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import EmailActionToken, User, UserSession

VERIFY_EMAIL = "VERIFY_EMAIL"
PASSWORD_RESET = "PASSWORD_RESET"
VERIFY_EMAIL_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=30)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_action_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_action_token(
    db: Session,
    user: User,
    *,
    purpose: str,
    ttl: timedelta,
) -> str:
    issued_at = now()
    # Only one live token per user/purpose is useful. Invalidate older unused
    # tokens before creating another one, so requesting a new email makes old
    # links harmless.
    previous = db.scalars(
        select(EmailActionToken).where(
            EmailActionToken.user_id == user.id,
            EmailActionToken.purpose == purpose,
            EmailActionToken.used_at.is_(None),
        )
    ).all()
    for row in previous:
        row.used_at = issued_at

    raw = secrets.token_urlsafe(32)
    db.add(
        EmailActionToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_action_token(raw),
            expires_at=issued_at + ttl,
        )
    )
    db.flush()
    return raw


def consume_action_token(db: Session, raw: str, *, purpose: str) -> tuple[EmailActionToken, User] | None:
    if not raw or len(raw) > 512:
        return None
    row = db.scalar(
        select(EmailActionToken).where(
            EmailActionToken.token_hash == hash_action_token(raw),
            EmailActionToken.purpose == purpose,
        )
    )
    if not row or row.used_at is not None or _as_utc(row.expires_at) <= now():
        return None
    user = db.get(User, row.user_id)
    if not user or user.disabled_at is not None:
        return None
    row.used_at = now()
    return row, user


def revoke_all_sessions(db: Session, user: User) -> int:
    revoked_at = now()
    rows = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
    ).all()
    for row in rows:
        row.revoked_at = revoked_at
    return len(rows)
