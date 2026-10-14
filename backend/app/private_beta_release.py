"""Fail-closed release boundary for the initial, still-disabled private beta."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .action_contract import action_kind
from .auth_models import Reviewer, ReviewerFamilyAuthorization
from .models import Action, AuditEvent, Case, Decision
from .private_beta_review import CHECKLIST_KEYS, facts_version
from .reviews import HumanReview


INITIAL_FAMILIES = frozenset({"E02-A", "C01"})
RELEASE_REASON = "PRE_BETA_EXTERNAL_RELEASE"
EXTERNAL_KINDS = frozenset({"prepare_outbound", "external_step", "workflow_submit"})
PENDING_RESPONSE = {"status": "PENDING_HUMAN_REVIEW", "reason": "External material is not released"}


def private_scope(case: Case) -> bool:
    return case.mode == "PRIVATE_REAL_BETA"


def actionable(action: Action) -> bool:
    return action_kind(action.type) in EXTERNAL_KINDS


def ensure_release_review(db: Session, case: Case, decision: Decision, action: Action) -> None:
    """Create one review for this exact diagnosis; keep all draft content internal."""
    if not private_scope(case) or case.family not in INITIAL_FAMILIES or not actionable(action):
        return
    existing = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case.id,
        HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    if (existing is not None and existing.context_json.get("decision_id") == decision.id
            and existing.context_json.get("diagnosis_action_id") == action.id
            and existing.context_json.get("facts_version") == facts_version(db, case.id)):
        case.status = "HUMAN_REVIEW"
        return
    if existing is not None:
        existing.status = "SUPERSEDED"
    from .services_v2 import audit
    review = HumanReview(
        case_id=case.id, reason=RELEASE_REASON, priority="HIGH",
        context_json={
            "decision_id": decision.id, "diagnosis_action_id": action.id,
            "facts_version": facts_version(db, case.id),
        },
    )
    db.add(review)
    case.status = "HUMAN_REVIEW"
    db.flush()
    audit(db, case.id, "PRE_BETA_RELEASE_REVIEW_REQUESTED", {
        "review_id": review.id, "decision_id": decision.id,
    })


def release_approved(db: Session, case: Case) -> bool:
    """Whether the current participant-facing result can be shown or acted on."""
    if not private_scope(case):
        return True
    if case.family not in INITIAL_FAMILIES or not case.current_decision_id:
        return False
    decision = db.get(Decision, case.current_decision_id)
    action = db.get(Action, case.current_action_id) if case.current_action_id else None
    if decision is None or decision.case_id != case.id or action is None or action.case_id != case.id:
        return False
    reviews = db.scalars(select(HumanReview).where(HumanReview.case_id == case.id)).all()
    if any(row.status == "OPEN" for row in reviews):
        return False
    if not actionable(action) or action.status not in {"OPEN", "READY"} or decision.viability not in {"HIGH", "MEDIUM"}:
        return False
    approvals = db.scalars(select(AuditEvent).where(
        AuditEvent.case_id == case.id,
        AuditEvent.event_type == "PRE_BETA_RELEASE_APPROVED",
    )).all()
    current_facts_version = facts_version(db, case.id)
    return any(
        row.reason == RELEASE_REASON
        and row.status == "COMPLETED"
        and row.assigned_reviewer_id is not None
        and row.reviewer_decision == "APPROVED_FOR_EXTERNAL_RELEASE"
        and row.context_json.get("decision_id") == decision.id
        and row.context_json.get("diagnosis_action_id") == action.id
        and row.context_json.get("facts_version") == current_facts_version
        and row.context_json.get("reason_code") == "CONFIRMED_AS_SUPPORTED"
        and all(row.context_json.get("checklist", {}).get(key) is True for key in CHECKLIST_KEYS)
        and (reviewer := db.get(Reviewer, row.assigned_reviewer_id)) is not None
        and reviewer.disabled_at is None
        and (authorization := db.scalar(select(ReviewerFamilyAuthorization).where(
            ReviewerFamilyAuthorization.reviewer_id == reviewer.id,
            ReviewerFamilyAuthorization.family == case.family,
        ))) is not None
        and any(event.actor_reviewer_id == row.assigned_reviewer_id
                and event.payload_json.get("review_id") == row.id
                and event.payload_json.get("decision_id") == decision.id
                and event.payload_json.get("action_id") == action.id
                and event.payload_json.get("facts_version") == current_facts_version
                and event.payload_json.get("authorization_id") == authorization.id
                and event.payload_json.get("reason_code") == "CONFIRMED_AS_SUPPORTED"
                for event in approvals)
        for row in reviews
    )


def require_release_approval(db: Session, case: Case) -> None:
    if private_scope(case) and not release_approved(db, case):
        raise HTTPException(409, "External material is pending authorized human review")
