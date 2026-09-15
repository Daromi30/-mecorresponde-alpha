from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, ForeignKey, String, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column

from .config import settings
from .db import Base, SessionLocal
from .models import Case


class CaseAccess(Base):
    __tablename__ = "case_access"

    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


_new_case_access: ContextVar[tuple[str, str] | None] = ContextVar(
    "mecorresponde_new_case_access", default=None
)
_CASE_PATH = re.compile(r"^/api/cases/([^/]+)(?:/|$)")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cookie_name(case_id: str) -> str:
    return f"mcr_case_{case_id}"


@event.listens_for(Case, "after_insert")
def _issue_access_after_case_insert(
    mapper, connection: Connection, target: Case  # noqa: ARG001
) -> None:
    """Issue one bearer secret when a case is created; only its hash is persisted."""
    token = secrets.token_urlsafe(32)
    connection.execute(
        CaseAccess.__table__.insert().values(
            case_id=target.id,
            token_hash=_hash_token(token),
            created_at=datetime.now(timezone.utc),
        )
    )
    _new_case_access.set((target.id, token))


def verify_case_access(case_id: str, token: str | None) -> bool:
    if not token:
        return False
    with SessionLocal() as db:
        row = db.get(CaseAccess, case_id)
        if row is None:
            return False
        return hmac.compare_digest(row.token_hash, _hash_token(token))


async def case_access_middleware(request: Request, call_next):
    """Protect case endpoints while keeping POST /api/cases open for no-login intake."""
    _new_case_access.set(None)
    match = _CASE_PATH.match(request.url.path)
    if (
        settings.case_access_required
        and match is not None
        and request.method.upper() != "OPTIONS"
    ):
        case_id = match.group(1)
        token = request.headers.get("X-Case-Token") or request.cookies.get(
            _cookie_name(case_id)
        )
        if not verify_case_access(case_id, token):
            return JSONResponse(status_code=404, content={"detail": "Case not found"})

    response = await call_next(request)

    issued = _new_case_access.get()
    if issued is not None and request.method.upper() == "POST" and request.url.path == "/api/cases" and response.status_code < 400:
        case_id, token = issued
        response.headers["X-Case-Token"] = token
        response.set_cookie(
            key=_cookie_name(case_id),
            value=token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path=f"/api/cases/{case_id}",
        )
    return response
