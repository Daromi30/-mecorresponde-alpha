from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import DateTime, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_user_from_request
from .config import settings
from .db import Base, get_db
from .models import AuditEvent, Case


class CaseAccess(Base):
    __tablename__ = "case_access"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def generate_case_token() -> str:
    return secrets.token_urlsafe(32)


def hash_case_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def case_cookie_name(case_id: str) -> str:
    return f"mcr_case_{case_id}"


def set_case_access_cookie(response: Response, case_id: str, token: str) -> None:
    response.set_cookie(
        key=case_cookie_name(case_id),
        value=token,
        httponly=True,
        secure=settings.render,
        samesite="strict",
        path=f"/api/cases/{case_id}",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_case_access_cookie(response: Response, case_id: str) -> None:
    response.delete_cookie(
        key=case_cookie_name(case_id),
        path=f"/api/cases/{case_id}",
        secure=settings.render,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def _block_case_user_review_completion(request: Request) -> None:
    """Keep human/professional review completion behind the protected backoffice."""
    path = request.url.path.rstrip("/")
    if (
        request.method.upper() == "POST"
        and "/reviews/" in path
        and path.endswith("/complete")
    ):
        raise HTTPException(
            status_code=403,
            detail="Human review can only be completed through the protected backoffice",
        )


def _block_locked_initial_mutation(request: Request, db: Session, case: Case) -> None:
    """Prevent case-owner endpoints from rewinding a case after the action phase starts.

    Once an initial claim was submitted, later evidence belongs to the response/review/
    outcome loop. Re-posting intake facts or rerunning initial diagnosis/claim preparation
    would otherwise reset status or create duplicate outbound actions. Internal response
    analysis and protected backoffice review call service functions directly and are not
    affected by this HTTP boundary.
    """
    if request.method.upper() != "POST":
        return

    path = request.url.path.rstrip("/")
    initial_mutation = path.endswith(("/facts", "/charges", "/diagnose", "/prepare-claim"))
    document_fact_confirmation = "/documents/" in path and path.endswith("/confirm-fact")
    if not (initial_mutation or document_fact_confirmation):
        return

    submitted = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    )
    protected_phase = case.status in {
        "HUMAN_REVIEW",
        "WAITING_RESPONSE",
        "RESPONSE_RECEIVED",
        "RESOLVED_PENDING_EXECUTION",
        "RESOLVED",
    }
    if submitted or protected_phase:
        raise HTTPException(
            status_code=409,
            detail=(
                "Initial case facts and claim actions are locked in the current phase; "
                "use the response, evidence, outcome, or protected review flow instead"
            ),
        )


def _enforce_authorized_case_boundaries(request: Request, db: Session, case: Case) -> None:
    _block_case_user_review_completion(request)
    _block_locked_initial_mutation(request, db, case)


def require_case_access(request: Request, db: Session = Depends(get_db)) -> None:
    """Protect case routes with either case capability or authenticated ownership."""
    case_id = request.path_params.get("case_id")
    if not case_id:
        return

    case = db.get(Case, case_id)
    user = get_user_from_request(request, db)
    if case and user and case.user_id == user.id:
        _enforce_authorized_case_boundaries(request, db, case)
        return

    access = db.get(CaseAccess, case_id)
    supplied = request.headers.get("X-Case-Token") or request.cookies.get(case_cookie_name(case_id))
    if not access or not supplied:
        raise HTTPException(status_code=404, detail="Case not found")

    supplied_hash = hash_case_token(supplied)
    if not hmac.compare_digest(supplied_hash, access.token_hash):
        # Return 404 instead of 401/403 so callers cannot use the endpoint to
        # discover whether a given case UUID exists.
        raise HTTPException(status_code=404, detail="Case not found")

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_authorized_case_boundaries(request, db, case)
