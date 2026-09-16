from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth_models import AuthThrottleState


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AuthThrottle:
    """Database-backed per-email action throttle using only a one-way digest.

    ``key_prefix`` namespaces different actions without storing the email or action
    label in the database. The empty prefix preserves the original login hashes so
    deploying this generalization does not reset an already-active login block.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        key_prefix: str = "",
        detail: str = "Too many authentication attempts. Try again later.",
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.detail = detail

    def _key(self, email: str) -> str:
        material = f"{self.key_prefix}:{email}" if self.key_prefix else email
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _window_end(self, row: AuthThrottleState) -> datetime:
        return _utc(row.window_started_at) + timedelta(seconds=self.window_seconds)

    def check(self, db: Session, email: str) -> None:
        row = db.get(AuthThrottleState, self._key(email))
        if not row:
            return

        current = datetime.now(timezone.utc)
        block_end = _utc(row.blocked_until) if row.blocked_until else self._window_end(row)
        if row.failure_count >= self.limit and block_end > current:
            retry_after = max(1, int((block_end - current).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail=self.detail,
                headers={"Retry-After": str(retry_after)},
            )

    def hit(self, db: Session, email: str) -> None:
        """Record an attempt/request in the current throttle window."""
        key = self._key(email)
        current = datetime.now(timezone.utc)

        # Keep the table bounded without retaining stale digests indefinitely.
        db.execute(
            delete(AuthThrottleState).where(
                AuthThrottleState.updated_at < current - timedelta(days=7)
            )
        )

        row = db.scalar(
            select(AuthThrottleState)
            .where(AuthThrottleState.key_hash == key)
            .with_for_update()
        )
        if row is None:
            row = AuthThrottleState(
                key_hash=key,
                failure_count=1,
                window_started_at=current,
                blocked_until=None,
                updated_at=current,
            )
            db.add(row)
            try:
                db.flush()
                return
            except IntegrityError:
                # Another worker may have created the row concurrently. Auth
                # request paths have no unrelated writes before this call.
                db.rollback()
                row = db.scalar(
                    select(AuthThrottleState)
                    .where(AuthThrottleState.key_hash == key)
                    .with_for_update()
                )
                if row is None:
                    raise

        if self._window_end(row) <= current:
            row.failure_count = 1
            row.window_started_at = current
            row.blocked_until = None
        else:
            row.failure_count += 1
            if row.failure_count >= self.limit:
                row.blocked_until = self._window_end(row)
        row.updated_at = current
        db.flush()

    def fail(self, db: Session, email: str) -> None:
        """Backward-compatible name for recording a failed authentication."""
        self.hit(db, email)

    def success(self, db: Session, email: str) -> None:
        db.execute(
            delete(AuthThrottleState).where(
                AuthThrottleState.key_hash == self._key(email)
            )
        )
        db.flush()

    def reset(self, db: Session) -> None:
        """Test/support helper; production code never globally resets throttles."""
        db.execute(delete(AuthThrottleState))
        db.flush()


class LoginThrottle(AuthThrottle):
    def __init__(self, limit: int = 8, window_seconds: int = 15 * 60):
        super().__init__(
            limit,
            window_seconds,
            detail="Too many login attempts. Try again later.",
        )


login_throttle = LoginThrottle()
password_reset_throttle = AuthThrottle(
    3,
    15 * 60,
    key_prefix="password-reset",
    detail="Too many recovery requests. Try again later.",
)
verification_email_throttle = AuthThrottle(
    3,
    15 * 60,
    key_prefix="email-verification",
    detail="Too many verification emails requested. Try again later.",
)
