"""One authorization boundary for every /api/admin route."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .auth_models import Reviewer, ReviewerSession
from .backoffice_auth import session_from_request
from .config import settings
from .db import get_db
from .models import Case
from .real_beta_gate import REAL_MODE, require_real_case_mutation
from .reviews import HumanReview
from .services_v2 import audit


@dataclass(frozen=True)
class AdminPrincipal:
    kind: str  # "reviewer" or "synthetic_bootstrap"
    reviewer: Reviewer | None = None
    session: ReviewerSession | None = None

    @property
    def actor_id(self) -> str | None:
        return self.reviewer.id if self.reviewer is not None else None


def _bootstrap_valid(authorization: str | None, x_admin_token: str | None) -> bool:
    expected = settings.admin_api_token.strip()
    supplied = x_admin_token
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:].strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def _denied(db: Session, case_id: str | None, actor_id: str | None, reason: str) -> None:
    audit(
        db, case_id, "BACKOFFICE_ACCESS_DENIED", {"reason": reason},
        actor_reviewer_id=actor_id,
    )
    db.commit()


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminPrincipal:
    """Reviewer cookie for private data; shared token only for legacy synthetic use.

    Path parameters are resolved centrally. Unlisted future admin routes default to
    reviewer-only, so adding a router cannot silently expose private data to the
    legacy token. Private reads are audit-committed before the handler can respond.
    """
    resolved = session_from_request(request, db)
    if resolved is not None:
        reviewer, session = resolved
        principal = AdminPrincipal("reviewer", reviewer, session)
    elif _bootstrap_valid(authorization, x_admin_token):
        principal = AdminPrincipal("synthetic_bootstrap")
    else:
        if not settings.admin_api_token.strip():
            raise HTTPException(503, "Backoffice is not configured")
        raise HTTPException(401, "Invalid backoffice credentials")

    request.state.admin_principal = principal
    path = request.url.path.rstrip("/")
    method = request.method.upper()

    if path.startswith("/api/admin/reviewers") or path.startswith("/api/admin/real-beta"):
        if principal.reviewer is None or principal.reviewer.role != "operator":
            _denied(db, None, principal.actor_id, "operator_required")
            raise HTTPException(403, "Operator session required")
        return principal

    case_id = request.path_params.get("case_id")
    review_id = request.path_params.get("review_id")
    review = db.get(HumanReview, review_id) if review_id else None
    if review is not None:
        case_id = review.case_id
    case = db.get(Case, case_id) if case_id else None

    if case is not None and case.mode == REAL_MODE:
        if principal.reviewer is None:
            _denied(db, case.id, None, "individual_session_required")
            raise HTTPException(404, "Case not found")
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if path.endswith("/assign") and principal.reviewer.role != "operator":
                _denied(db, case.id, principal.actor_id, "operator_assignment_required")
                raise HTTPException(403, "Operator session required")
            if (review is not None and review.assigned_reviewer_id is not None
                    and principal.reviewer.role == "reviewer"
                    and review.assigned_reviewer_id != principal.actor_id):
                _denied(db, case.id, principal.actor_id, "assigned_reviewer_required")
                raise HTTPException(403, "Review is assigned to another reviewer")
            try:
                require_real_case_mutation(db, case)
            except HTTPException:
                _denied(db, case.id, principal.actor_id, "private_gate_closed")
                raise
        else:
            event_type = "BACKOFFICE_HANDOFF_READ" if path.endswith("/handoff") else "BACKOFFICE_CASE_READ"
            audit(db, case.id, event_type, {}, actor_reviewer_id=principal.actor_id)
            # A failed commit aborts the request before any private data is returned.
            db.commit()
        return principal

    # Only enumerated non-case endpoints remain usable with the shared token.
    synthetic_paths = {
        "/api/admin/health", "/api/admin/stats", "/api/admin/reviews",
        "/api/admin/readiness", "/api/admin/review-routing/families",
    }
    if principal.reviewer is None and case is None and path not in synthetic_paths:
        raise HTTPException(403, "Individual backoffice session required")
    return principal
