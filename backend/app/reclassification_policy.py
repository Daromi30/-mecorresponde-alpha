from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .family_manifest import FAMILY_MANIFEST
from .models import Action, Case, Decision


_INSTALLED = False
_MAX_RECLASSIFICATION_HOPS = 4

# Only transitions whose destination is unambiguous from an existing evaluator result
# are automated. Never derive a target family from an arbitrary action string.
_REGISTERED_TRANSITIONS: dict[tuple[str, str], str] = {
    ("C01", "RECLASSIFY_C02"): "C02",
    ("C02", "RECLASSIFY_C01"): "C01",
    ("E04-A", "RECLASSIFY_CONTRACTED_ADDON"): "E04-B",
    ("E04-B", "RECLASSIFY_E04A"): "E04-A",
    ("E06", "RECLASSIFY_E02_A"): "E02-A",
}


def _complete_reclassification_action(action: Action) -> None:
    if action.status not in {"COMPLETED", "SUPERSEDED"}:
        action.status = "COMPLETED"
        action.completed_at = datetime.now(timezone.utc)


def _route_unregistered_reclassification_to_review(
    db: Session,
    case: Case,
    *,
    source_family: str,
    result: Any,
    decision_id: str,
    source_action: Action,
    reason: str,
) -> Action:
    _complete_reclassification_action(source_action)
    review = svc.create_human_review(
        db,
        case,
        reason="ENGINE_RECLASSIFICATION_REVIEW",
        priority="HIGH",
        context={
            "phase": "ENGINE_RECLASSIFICATION",
            "reason": reason,
            "source_family": source_family,
            "scope_status": result.scope_status,
            "requested_action": result.next_action,
            "source_decision_id": decision_id,
            "source_action_id": source_action.id,
        },
    )
    db.flush()
    review_action = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="OPEN",
        payload_json={
            "reason": review.reason,
            "review_id": review.id,
            "phase": "ENGINE_RECLASSIFICATION",
            "source_family": source_family,
            "requested_action": result.next_action,
            "decision_id": decision_id,
        },
    )
    db.add(review_action)
    db.flush()
    case.current_action_id = review_action.id
    case.status = "HUMAN_REVIEW"
    svc.audit(
        db,
        case.id,
        "ENGINE_RECLASSIFICATION_REVIEW_REQUIRED",
        {
            "review_id": review.id,
            "review_action_id": review_action.id,
            "source_family": source_family,
            "scope_status": result.scope_status,
            "requested_action": result.next_action,
            "source_decision_id": decision_id,
            "source_action_id": source_action.id,
            "reason": reason,
        },
    )
    db.commit()
    return review_action


def _requests_reclassification(result: Any) -> bool:
    """Recognize routing intent from either the explicit viability or action contract.

    Some evaluators historically emitted a RECLASSIFY_* action together with LOW or
    OUT_OF_SCOPE viability. The action is still a routing transition: leaving it as an
    ordinary DIAGNOSED action strands the case because claimant UI must never guess the
    destination. Registered transitions are executed; every other RECLASSIFY_* action
    fails closed to protected human review.
    """
    return result.viability == "RECLASSIFY" or str(result.next_action or "").startswith("RECLASSIFY_")


def install_reclassification_policy() -> None:
    """Resolve registered family redirects and fail closed for every other reclassification.

    The policy is installed before the post-response diagnosis wrapper. That ordering is
    intentional: if a company response causes a deterministic family redirect, the outer
    post-response guard still sees the final diagnosis and can block any attempt to repeat
    the initial outbound claim.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_diagnose = svc.diagnose

    def diagnose_with_registered_reclassification(db: Session, case: Case):
        visited_families: list[str] = []
        last_reclassification: tuple[str, Any, Decision, Action] | None = None

        for _ in range(_MAX_RECLASSIFICATION_HOPS):
            source_family = case.family or ""
            result, decision, action = previous_diagnose(db, case)
            if not _requests_reclassification(result):
                return result, decision, action

            last_reclassification = (source_family, result, decision, action)
            target_family = _REGISTERED_TRANSITIONS.get((source_family, result.next_action))
            if (
                target_family is None
                or target_family == source_family
                or target_family not in FAMILY_MANIFEST
                or target_family in visited_families
            ):
                review_action = _route_unregistered_reclassification_to_review(
                    db,
                    case,
                    source_family=source_family,
                    result=result,
                    decision_id=decision.id,
                    source_action=action,
                    reason=(
                        "unregistered_or_same_family_transition"
                        if target_family is None or target_family == source_family
                        else "reclassification_cycle_detected"
                    ),
                )
                return result, decision, review_action

            _complete_reclassification_action(action)
            target = FAMILY_MANIFEST[target_family]
            visited_families.append(source_family)
            case.family = target.code
            case.vertical = target.vertical
            case.title = target.title
            case.status = "INTAKE"
            case.current_decision_id = None
            case.current_action_id = None
            svc.audit(
                db,
                case.id,
                "CASE_RECLASSIFIED_BY_ENGINE",
                {
                    "from_family": source_family,
                    "to_family": target.code,
                    "requested_action": result.next_action,
                    "source_decision_id": decision.id,
                    "source_action_id": action.id,
                    "hop": len(visited_families),
                },
            )
            # Persist the safe routing transition before asking the target evaluator to
            # run. If that evaluator unexpectedly fails, the case remains recoverable in
            # INTAKE under the target family instead of being stranded in REANALYZING.
            db.commit()
            db.refresh(case)

        # A chain longer than the explicit bound is operationally unsafe even if every
        # individual edge was registered. Do not execute one more diagnosis just to detect
        # it: use the last proven redirect as the review handoff context.
        assert last_reclassification is not None
        source_family, result, decision, action = last_reclassification
        review_action = _route_unregistered_reclassification_to_review(
            db,
            case,
            source_family=source_family,
            result=result,
            decision_id=decision.id,
            source_action=action,
            reason="maximum_reclassification_hops_exceeded",
        )
        return result, decision, review_action

    svc.diagnose = diagnose_with_registered_reclassification
    _INSTALLED = True
