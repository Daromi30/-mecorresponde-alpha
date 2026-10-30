"""Conservative invalidation of outputs derived from a superseded case state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Action, Case, Decision
from .reviews import HumanReview


def invalidate_case_derivatives(
    db: Session,
    case: Case,
    *,
    reason: str,
    mutation: str,
    fact_key: str | None = None,
    source: str | None = None,
    exclude_review_ids: frozenset[str] = frozenset(),
) -> dict[str, list[str]]:
    """Invalidate current derived material without deleting its audit history.

    The caller owns the surrounding transaction. Values and payloads are deliberately
    absent from the audit event; only row identifiers and the mutation class are stored.
    """
    from .services_v2 import audit

    moment = datetime.now(timezone.utc)
    previous_decision_id = case.current_decision_id
    previous_action_id = case.current_action_id
    decisions = db.scalars(select(Decision).where(
        Decision.case_id == case.id,
        Decision.invalidated_at.is_(None),
    )).all()
    for decision in decisions:
        decision.invalidated_at = moment

    actions = db.scalars(select(Action).where(
        Action.case_id == case.id,
        Action.status.not_in({"COMPLETED", "SUPERSEDED"}),
    )).all()
    for action in actions:
        action.status = "SUPERSEDED"
        action.completed_at = moment

    reviews = db.scalars(select(HumanReview).where(
        HumanReview.case_id == case.id,
        HumanReview.status == "OPEN",
        HumanReview.id.not_in(exclude_review_ids),
    )).all()
    for review in reviews:
        review.status = "SUPERSEDED"
        review.completed_at = moment
        review.context_json = {
            **(review.context_json or {}),
            "invalidation_reason": reason,
            "invalidation_mutation": mutation,
        }

    result = {
        "decision_ids": [row.id for row in decisions],
        "action_ids": [row.id for row in actions],
        "review_ids": [row.id for row in reviews],
    }
    if any(result.values()):
        audit(db, case.id, "DERIVED_OUTPUTS_INVALIDATED", {
            "reason": reason,
            "mutation": mutation,
            **result,
        })
    if fact_key is not None and source is not None and (previous_decision_id or previous_action_id):
        audit(db, case.id, "CURRENT_ANALYSIS_SUPERSEDED", {
            "fact_key": fact_key,
            "source": source,
            "previous_action_id": previous_action_id,
            "previous_decision_id": previous_decision_id,
        })
    case.current_decision_id = None
    case.current_action_id = None
    return result
