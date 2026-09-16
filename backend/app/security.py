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
from .models import Action, AuditEvent, Case


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


def _block_legacy_untraced_resolution_routes(request: Request) -> None:
    """Require evidence-aware HTTP routes for responses and outcomes."""
    if request.method.upper() != "POST":
        return
    path = request.url.path.rstrip("/")
    if path.endswith("/responses"):
        raise HTTPException(
            status_code=409,
            detail="Use the evidenced company-response endpoint for this case",
        )
    if path.endswith("/outcome"):
        raise HTTPException(
            status_code=409,
            detail="Use the evidenced outcome endpoint for this case",
        )


def _require_prepared_claim_before_submission(request: Request, db: Session, case: Case) -> None:
    if request.method.upper() != "POST" or not request.url.path.rstrip("/").endswith("/submission"):
        return
    current = db.get(Action, case.current_action_id) if case.current_action_id else None
    if (
        case.status != "READY_TO_SUBMIT"
        or current is None
        or current.case_id != case.id
        or current.type != "SUBMIT_INITIAL_CLAIM"
        or current.status != "READY"
    ):
        raise HTTPException(
            status_code=409,
            detail="The initial claim must be diagnosed and prepared before its submission can be recorded",
        )


def _require_new_fact_before_missing_information_replay(request: Request, case: Case) -> None:
    """Do not rerun the same incomplete claimant snapshot.

    A claimant fact/document update already supersedes the prior analysis and moves the
    case back to INTAKE. Other phases keep their existing, more specific guards: the Motor
    rejects duplicate diagnosis after DIAGNOSED and the locked-phase boundary protects
    submitted, response, review and resolved cases.
    """
    if request.method.upper() != "POST" or not request.url.path.rstrip("/").endswith("/diagnose"):
        return
    if case.status == "NEEDS_INFORMATION":
        raise HTTPException(
            status_code=409,
            detail="Update the case facts before requesting a new diagnosis",
        )


def _block_locked_initial_mutation(request: Request, db: Session, case: Case) -> None:
    """Prevent case-owner endpoints from rewinding a case after the action phase starts."""
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
    allow_existing_prepare_gate = (
        not submitted
        and case.status == "HUMAN_REVIEW"
        and path.endswith("/prepare-claim")
    )
    if submitted or (protected_phase and not allow_existing_prepare_gate):
        raise HTTPException(
            status_code=409,
            detail=(
                "Initial case facts and claim actions are locked in the current phase; "
                "use the response, evidence, outcome, or protected review flow instead"
            ),
        )


def _enforce_authorized_case_boundaries(request: Request, db: Session, case: Case) -> None:
    _block_case_user_review_completion(request)
    _block_legacy_untraced_resolution_routes(request)
    _require_prepared_claim_before_submission(request, db, case)
    _block_locked_initial_mutation(request, db, case)
    _require_new_fact_before_missing_information_replay(request, case)


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
        raise HTTPException(status_code=404, detail="Case not found")

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_authorized_case_boundaries(request, db, case)
