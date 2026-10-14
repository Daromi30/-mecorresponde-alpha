"""Case-scoped, version-bound technical review of the first private-beta families."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import Reviewer, ReviewerFamilyAuthorization
from .models import Action, Case, Decision, Fact
from .reviews import HumanReview


REASON_CODES = frozenset({
    "CONFIRMED_AS_SUPPORTED", "INSUFFICIENT_INFORMATION", "FACT_CORRECTION_REQUIRED",
    "DIAGNOSIS_REJECTED", "ACTION_BLOCKED", "LEGAL_UNCERTAINTY",
    "OUT_OF_SCOPE", "ESCALATION_REQUIRED",
})
CHECKLIST_KEYS = (
    "facts_reviewed", "sources_rules_reviewed", "uncertainty_reviewed",
    "decision_reviewed", "action_reviewed",
)


def facts_version(db: Session, case_id: str) -> str:
    """Bind a review to the current fact row IDs without copying values to audit."""
    rows = db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at, Fact.id)).all()
    latest = {row.key: row.id for row in rows}
    encoded = "\n".join(f"{key}:{latest[key]}" for key in sorted(latest))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def family_authorized(db: Session, reviewer: Reviewer | None, family: str | None) -> bool:
    return bool(
        reviewer is not None and reviewer.disabled_at is None and family in {"E02-A", "C01"}
        and db.scalar(select(ReviewerFamilyAuthorization.id).where(
            ReviewerFamilyAuthorization.reviewer_id == reviewer.id,
            ReviewerFamilyAuthorization.family == family,
        )) is not None
    )


def require_assigned_reviewer(db: Session, review: HumanReview, case: Case, reviewer: Reviewer | None) -> None:
    if (review.status != "OPEN" or reviewer is None or reviewer.id != review.assigned_reviewer_id
            or not family_authorized(db, reviewer, case.family)):
        raise HTTPException(403, "Assigned, family-authorized reviewer session required")


def bind_current_version(db: Session, review: HumanReview, case: Case) -> None:
    review.context_json = {
        **(review.context_json or {}),
        "decision_id": case.current_decision_id,
        "diagnosis_action_id": case.current_action_id,
        "facts_version": facts_version(db, case.id),
    }


def require_current_version(db: Session, review: HumanReview, case: Case) -> tuple[Decision | None, Action | None]:
    context = review.context_json or {}
    decision = db.get(Decision, case.current_decision_id) if case.current_decision_id else None
    action = db.get(Action, case.current_action_id) if case.current_action_id else None
    if (review.case_id != case.id or context.get("decision_id") != case.current_decision_id
            or context.get("diagnosis_action_id") != case.current_action_id
            or context.get("facts_version") != facts_version(db, case.id)
            or (decision is not None and decision.case_id != case.id)
            or (action is not None and action.case_id != case.id)):
        raise HTTPException(409, "Review is stale; a new review of the current version is required")
    return decision, action


def record_resolution(review: HumanReview, outcome: str, reason_code: str,
                      *, checklist: dict[str, bool] | None = None) -> None:
    review.status = "COMPLETED"
    review.reviewer_decision = outcome
    review.completed_at = datetime.now(timezone.utc)
    review.context_json = {
        **(review.context_json or {}), "outcome": outcome,
        "reason_code": reason_code, "checklist": checklist or {},
    }
