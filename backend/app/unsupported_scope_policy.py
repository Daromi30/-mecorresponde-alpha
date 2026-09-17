from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case


_INSTALLED = False


def install_unsupported_scope_policy() -> None:
    """Keep known-family cases recoverable when the automated legal scope does not apply.

    A family evaluator can conclusively determine that its automated consumer regime is
    unsupported without proving that the underlying real-world problem has no remedy. In
    that situation the claimant UI must not be left with an inert REDIRECT_* action and the
    Motor must not invent a destination. Complete the generated routing action and hand the
    exact diagnosis to protected human review instead.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_diagnose = svc.diagnose

    def diagnose_with_assisted_unsupported_scope(db: Session, case: Case):
        result, decision, generated_action = previous_diagnose(db, case)
        if not (
            result.viability == "OUT_OF_SCOPE"
            and result.scope_status == "UNSUPPORTED"
        ):
            return result, decision, generated_action

        if generated_action.status not in {"COMPLETED", "SUPERSEDED"}:
            generated_action.status = "COMPLETED"
            generated_action.completed_at = datetime.now(timezone.utc)

        reason = "ENGINE_UNSUPPORTED_SCOPE"
        review = svc.create_human_review(
            db,
            case,
            reason=reason,
            priority="NORMAL",
            context={
                "phase": "ENGINE_SCOPE_FALLBACK",
                "family": case.family,
                "scope_status": result.scope_status,
                "viability": result.viability,
                "requested_action": result.next_action,
                "source_decision_id": decision.id,
                "source_action_id": generated_action.id,
            },
        )
        db.flush()
        review_action = Action(
            case_id=case.id,
            type="HUMAN_REVIEW",
            status="OPEN",
            payload_json={
                "reason": reason,
                "review_id": review.id,
                "phase": "ENGINE_SCOPE_FALLBACK",
                "family": case.family,
                "requested_action": result.next_action,
                "decision_id": decision.id,
            },
        )
        db.add(review_action)
        db.flush()
        case.current_action_id = review_action.id
        case.status = "HUMAN_REVIEW"
        svc.audit(
            db,
            case.id,
            "ENGINE_UNSUPPORTED_SCOPE_REVIEW_REQUIRED",
            {
                "review_id": review.id,
                "review_action_id": review_action.id,
                "family": case.family,
                "scope_status": result.scope_status,
                "viability": result.viability,
                "requested_action": result.next_action,
                "source_decision_id": decision.id,
                "source_action_id": generated_action.id,
            },
        )
        db.commit()
        db.refresh(case)
        return result, decision, review_action

    svc.diagnose = diagnose_with_assisted_unsupported_scope
    _INSTALLED = True
