from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_auth import AdminPrincipal, require_admin
from ..case_lifecycle import complete_current_action, set_current_action
from ..case_locking import lock_case_for_update
from ..db import get_db
from ..derived_invalidation import invalidate_case_derivatives
from ..evidence_context import atomic_workflow_transaction
from ..family_manifest import FAMILY_MANIFEST
from ..models import Action, Calculation, Case, Decision, Evidence, Fact, LegalRuleVersion, LegalSource, RuleEvaluation
from ..private_beta_fields import FIELD_SCHEMA, validate_private_fact
from ..private_beta_release import RELEASE_REASON, INITIAL_FAMILIES, actionable, release_approved
from ..private_beta_review import (
    bind_current_version, facts_version, record_resolution, require_assigned_reviewer,
    require_current_version,
)
from ..reviews import HumanReview
from ..services_v2 import EVALUATORS, audit, create_human_review, diagnose, get_next_question


router = APIRouter(
    prefix="/api/admin",
    tags=["admin-review-resolution"],
    dependencies=[Depends(require_admin)],
)


_RESERVED_FACT_PREFIXES = (
    "system.",
    "legal.",
    "rule.",
    "decision.",
    "action.",
)
_POST_RESPONSE_REVIEW_REASONS = {
    "POST_DENIAL_ESCALATION_REVIEW",
    "PROFESSIONAL_ESCALATION_REQUIRED",
}


class HumanFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=160)
    value: Any = None
    state: Literal["confirmed", "unknown"] = "confirmed"
    materiality: Literal["critical", "relevant", "context"] = "critical"
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        key = value.strip()
        if "." not in key:
            raise ValueError("Structured human facts must use a namespaced fact key")
        if key.casefold().startswith(_RESERVED_FACT_PREFIXES):
            raise ValueError("Reserved fact namespace cannot be set by human review")
        return key


class StructuredReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_decision: str | None = Field(default=None, min_length=3, max_length=10000)
    fact_updates: list[HumanFactUpdate] = Field(min_length=1, max_length=25)
    # Structured human review changes facts; the legal conclusion must therefore be
    # regenerated immediately by the deterministic Motor. There is no supported dormant
    # REANALYZING queue, so accepting False would create an operational dead end.
    reanalyze: Literal[True] = True
    reason_code: Literal["FACT_CORRECTION_REQUIRED"] | None = None

    @field_validator("fact_updates")
    @classmethod
    def unique_fact_keys(cls, value: list[HumanFactUpdate]) -> list[HumanFactUpdate]:
        keys = [item.key for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Each fact key can be updated only once per review resolution")
        return value


class AssistedReclassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_family: str = Field(min_length=2, max_length=20)
    reviewer_decision: str = Field(min_length=3, max_length=10000)

    @field_validator("target_family")
    @classmethod
    def validate_target_family(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in FAMILY_MANIFEST:
            raise ValueError("Target family is not registered in the Resolution Engine")
        return code


class ProfessionalEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_decision: str = Field(min_length=3, max_length=10000)


class ReviewChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    facts_reviewed: StrictBool
    sources_rules_reviewed: StrictBool
    uncertainty_reviewed: StrictBool
    decision_reviewed: StrictBool
    action_reviewed: StrictBool

    def complete(self) -> bool:
        return all(value is True for value in self.model_dump().values())


class ReleaseApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checklist: ReviewChecklist
    reason_code: Literal["CONFIRMED_AS_SUPPORTED"]


class PrivateReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["REQUEST_INFORMATION", "REJECT_DIAGNOSIS", "BLOCK_ACTION", "ESCALATE"]
    reason_code: Literal[
        "INSUFFICIENT_INFORMATION", "DIAGNOSIS_REJECTED", "ACTION_BLOCKED",
        "LEGAL_UNCERTAINTY", "OUT_OF_SCOPE", "ESCALATION_REQUIRED",
    ]
    requested_fields: list[str] = Field(default_factory=list, max_length=1)


def _review_or_404(db: Session, review_id: str) -> HumanReview:
    review = db.get(HumanReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def _complete_review_row(review: HumanReview, reviewer_decision: str) -> None:
    review.status = "COMPLETED"
    review.reviewer_decision = reviewer_decision.strip()
    review.completed_at = datetime.now(timezone.utc)


@router.get("/reviews/{review_id}/context")
def private_review_context(review_id: str, db: Session = Depends(get_db),
                           principal: AdminPrincipal = Depends(require_admin)) -> dict[str, Any]:
    """Show only this case's current structured material before any resolution."""
    review = _review_or_404(db, review_id)
    case = db.get(Case, review.case_id)
    if case is None or case.mode != "PRIVATE_REAL_BETA" or case.family not in INITIAL_FAMILIES:
        raise HTTPException(409, "Private review context unavailable")
    require_assigned_reviewer(db, review, case, principal.reviewer)
    decision, action = require_current_version(db, review, case)
    facts = db.scalars(select(Fact).where(Fact.case_id == case.id).order_by(Fact.created_at, Fact.id)).all()
    current_facts = {fact.key: fact for fact in facts}
    evidence = db.scalars(select(Evidence).where(Evidence.case_id == case.id)).all()
    evidence_by_fact: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        if item.fact_id:
            evidence_by_fact.setdefault(item.fact_id, []).append({
                "source_type": item.source_type, "strength": item.strength,
            })
    evaluation_refs = decision.rule_evaluations_json if decision else []
    evaluation_ids = {item.get("rule_evaluation_id") for item in evaluation_refs}
    evaluation_ids.discard(None)
    current_evaluations = db.scalars(select(RuleEvaluation).where(
        RuleEvaluation.case_id == case.id, RuleEvaluation.id.in_(evaluation_ids)
    )).all() if evaluation_ids else []
    if len(current_evaluations) != len(evaluation_refs):
        raise HTTPException(409, "Diagnosis rule evaluations are not version-bound")
    calculation_ids = {item.get("calculation_id") for item in evaluation_refs}
    calculation_ids.discard(None)
    if len(calculation_ids) > 1:
        raise HTTPException(409, "Diagnosis calculation binding is inconsistent")
    calculation = db.scalar(select(Calculation).where(
        Calculation.case_id == case.id, Calculation.id.in_(calculation_ids)
    )) if calculation_ids else None
    if calculation_ids and calculation is None:
        raise HTTPException(409, "Diagnosis calculation is not available")
    rule_refs = {(item["rule_id"], item["version"]) for item in evaluation_refs}
    rule_ids = {rule_id for rule_id, _version in rule_refs}
    versions = db.scalars(select(LegalRuleVersion).where(LegalRuleVersion.rule_id.in_(rule_ids))).all() if rule_ids else []
    current_versions = {row.rule_id: row for row in versions if (row.rule_id, row.version) in rule_refs}
    sources = []
    for rule in current_versions.values():
        source = db.get(LegalSource, rule.source_id)
        if source:
            sources.append({
                "rule_id": rule.rule_id, "version": rule.version,
                "article": rule.article, "title": source.title,
                "official_url": source.official_url, "status": source.status,
            })
    latest_evaluations = {row.id: row for row in current_evaluations}
    return {
        "case_id": case.id, "family": case.family, "case_status": case.status,
        "review_id": review.id, "review_reason": review.reason,
        "review_status": review.status, "assigned_reviewer_id": review.assigned_reviewer_id,
        "technical_reviewer_authorization": case.family,
        "professional_legal_qualification": "NOT_ASSERTED",
        "requestable_fields": [
            {"key": key, "input_type": kind}
            for key, (kind, _required) in FIELD_SCHEMA[case.family].items()
        ],
        "facts_version": facts_version(db, case.id),
        "facts": [{
            "id": fact.id, "key": fact.key, "value": fact.value_json.get("value"),
            "state": fact.state, "user_confirmed": fact.user_confirmed,
            "created_by": fact.created_by, "evidence": evidence_by_fact.get(fact.id, []),
        } for fact in sorted(current_facts.values(), key=lambda row: row.key)],
        "decision": None if decision is None else {
            "id": decision.id, "viability": decision.viability,
            "scope_status": decision.scope_status, "claimable_amount": decision.claimable_amount,
            "economic_value": decision.economic_value, "worth_pursuing": decision.worth_pursuing,
            "reasoning_summary": decision.reasoning_summary,
            "counterarguments": decision.counterarguments_snapshot,
            "rule_evaluations": decision.rule_evaluations_json,
        },
        "action": None if action is None else {
            "id": action.id, "type": action.type, "status": action.status,
            "payload": action.payload_json,
        },
        "calculation": None if calculation is None else {
            "id": calculation.id, "type": calculation.type, "inputs": calculation.inputs_json,
            "result": calculation.result, "formula_version": calculation.formula_version,
        },
        "rule_evaluations": [{
            "id": row.id, "rule_version_id": row.rule_version_id,
            "result": row.result, "missing_facts": row.missing_conditions,
            "failed_conditions": row.failed_conditions,
        } for row in latest_evaluations.values()],
        "sources": sources,
        "remedies": (action.payload_json or {}).get("remedies", []) if action else [],
        "burden_of_proof": (action.payload_json or {}).get("burden_of_proof", []) if action else [],
        "uncertainties": {
            "counterarguments": decision.counterarguments_snapshot if decision else [],
            "missing_facts": [value for row in latest_evaluations.values() for value in row.missing_conditions],
            "failed_conditions": [value for row in latest_evaluations.values() for value in row.failed_conditions],
        },
    }


@router.post("/reviews/{review_id}/approve-release")
def approve_private_release(
    review_id: str,
    payload: ReleaseApproval,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, str]:
    """Approve one current diagnosis, never a future or changed fact snapshot."""
    review = _review_or_404(db, review_id)
    case = lock_case_for_update(db, review.case_id)
    if case is None or case.mode != "PRIVATE_REAL_BETA" or case.family not in INITIAL_FAMILIES:
        raise HTTPException(409, "Private release is unavailable")
    require_assigned_reviewer(db, review, case, principal.reviewer)
    decision, action = require_current_version(db, review, case)
    if not payload.checklist.complete():
        raise HTTPException(422, "All substantive review checks must be explicitly true")
    if (
        review.reason != RELEASE_REASON or review.status != "OPEN"
        or decision is None or action is None
        or decision.case_id != case.id or action.case_id != case.id
        or decision.viability not in {"HIGH", "MEDIUM"}
        or not actionable(action) or action.status not in {"OPEN", "READY"}
        or review.context_json.get("decision_id") != decision.id
        or review.context_json.get("diagnosis_action_id") != action.id
        or case.status != "HUMAN_REVIEW"
    ):
        raise HTTPException(409, "Current diagnosis cannot be released")
    other_open = db.scalar(select(HumanReview.id).where(
        HumanReview.case_id == case.id,
        HumanReview.id != review.id,
        HumanReview.status == "OPEN",
    ))
    if other_open is not None:
        raise HTTPException(409, "Other human review remains pending")
    with atomic_workflow_transaction(db) as commit:
        from ..auth_models import ReviewerFamilyAuthorization
        authorization = db.scalar(select(ReviewerFamilyAuthorization).where(
            ReviewerFamilyAuthorization.reviewer_id == principal.actor_id,
            ReviewerFamilyAuthorization.family == case.family,
        ))
        if authorization is None:
            raise HTTPException(403, "Family authorization is required")
        record_resolution(review, "APPROVED_FOR_EXTERNAL_RELEASE", payload.reason_code,
                          checklist=payload.checklist.model_dump())
        case.status = "READY_TO_SUBMIT" if action.type == "SUBMIT_INITIAL_CLAIM" else "DIAGNOSED"
        audit(db, case.id, "PRE_BETA_RELEASE_APPROVED", {
            "review_id": review.id, "decision_id": decision.id, "action_id": action.id,
            "facts_version": facts_version(db, case.id),
            "reason_code": payload.reason_code, "outcome": "APPROVED_FOR_EXTERNAL_RELEASE",
            "authorization_id": authorization.id,
        }, actor_reviewer_id=principal.actor_id)
        db.flush()
        if not release_approved(db, case):
            raise HTTPException(409, "Private release approval could not be verified")
        commit()
    return {"status": "RELEASED", "decision_id": decision.id}


@router.post("/reviews/{review_id}/resolve-private")
def resolve_private_review(review_id: str, payload: PrivateReviewResolution,
                           db: Session = Depends(get_db),
                           principal: AdminPrincipal = Depends(require_admin)) -> dict[str, Any]:
    """Non-approval outcomes never manufacture a replacement legal conclusion."""
    review = _review_or_404(db, review_id)
    case = lock_case_for_update(db, review.case_id)
    if case is None or case.mode != "PRIVATE_REAL_BETA" or case.family not in INITIAL_FAMILIES:
        raise HTTPException(409, "Private review resolution unavailable")
    require_assigned_reviewer(db, review, case, principal.reviewer)
    decision, action = require_current_version(db, review, case)
    allowed_reasons = {
        "REQUEST_INFORMATION": {"INSUFFICIENT_INFORMATION"},
        "REJECT_DIAGNOSIS": {"DIAGNOSIS_REJECTED", "OUT_OF_SCOPE"},
        "BLOCK_ACTION": {"ACTION_BLOCKED"},
        "ESCALATE": {"LEGAL_UNCERTAINTY", "ESCALATION_REQUIRED"},
    }
    if payload.reason_code not in allowed_reasons[payload.outcome]:
        raise HTTPException(422, "Reason code does not match outcome")
    if payload.outcome == "REQUEST_INFORMATION":
        if (not payload.requested_fields or len(payload.requested_fields) != len(set(payload.requested_fields))
                or any(key not in FIELD_SCHEMA[case.family] for key in payload.requested_fields)):
            raise HTTPException(422, "Request only distinct, allowlisted structured fields")
    elif payload.requested_fields:
        raise HTTPException(422, "Requested fields are only valid for information requests")
    if payload.outcome == "BLOCK_ACTION" and action is None:
        raise HTTPException(409, "No current action to block")

    with atomic_workflow_transaction(db) as commit:
        prior = {
            "review_id": review.id, "decision_id": case.current_decision_id,
            "action_id": case.current_action_id,
            "facts_version": facts_version(db, case.id),
            "outcome": payload.outcome, "reason_code": payload.reason_code,
        }
        if action is not None:
            action.status = "SUPERSEDED"
        record_resolution(review, payload.outcome, payload.reason_code)
        if payload.outcome == "REQUEST_INFORMATION":
            review.context_json = {**review.context_json, "requested_fields": payload.requested_fields}
            case.current_decision_id = None
            case.current_action_id = None
            case.status = "NEEDS_INFORMATION"
            prior["requested_fields"] = payload.requested_fields
        else:
            if payload.outcome == "REJECT_DIAGNOSIS":
                case.current_decision_id = None
                case.current_action_id = None
                followup_reason = "PRIVATE_BETA_DIAGNOSIS_REJECTED"
            elif payload.outcome == "BLOCK_ACTION":
                case.current_action_id = None
                followup_reason = "PRIVATE_BETA_ACTION_BLOCKED"
            else:
                case.current_action_id = None
                followup_reason = "PRIVATE_BETA_PROFESSIONAL_REVIEW_REQUIRED"
            followup = create_human_review(db, case, followup_reason, "HIGH", {
                "source_review_id": review.id, "family": case.family,
            })
            db.flush()
            bind_current_version(db, followup, case)
            case.status = "HUMAN_REVIEW"
            prior["followup_review_id"] = followup.id
        audit(db, case.id, "PRIVATE_BETA_REVIEW_RESOLVED", prior,
              actor_reviewer_id=principal.actor_id)
        commit()
    return {"review_id": review.id, "outcome": payload.outcome,
            "case_id": case.id, "case_status": case.status, "released": False}


@router.get("/review-routing/families")
def review_routing_families() -> dict[str, list[dict[str, str]]]:
    """Expose only the registered routing targets available to assisted review."""
    return {
        "families": [
            {
                "code": entry.code,
                "vertical": entry.vertical,
                "title": entry.title,
            }
            for entry in FAMILY_MANIFEST.values()
        ]
    }


@router.post("/reviews/{review_id}/reclassify")
def reclassify_unsupported_review(
    review_id: str,
    payload: AssistedReclassification,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, Any]:
    """Route an unsupported intake into one existing family without deciding the law.

    This endpoint is deliberately narrow: it can only resolve the fallback review created
    for an unclassified intake, and only to a family already registered in the Motor. It
    does not set legal facts, viability, remedies, amounts, deadlines or authorities.
    """
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    if review.reason != "UNSUPPORTED_CLASSIFICATION":
        raise HTTPException(status_code=409, detail="This review is not an unsupported-intake routing review")

    case = lock_case_for_update(db, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.family is not None:
        raise HTTPException(status_code=409, detail="Case is already assigned to a resolution family")
    if case.status != "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="Case is no longer waiting for assisted classification")

    if case.mode == "PRIVATE_REAL_BETA":
        require_assigned_reviewer(db, review, case, principal.reviewer)
        require_current_version(db, review, case)
        from ..real_beta_gate import allowed_families, audit_once
        if payload.target_family not in allowed_families():
            audit_once(db, case.id, "REAL_BETA_FAMILY_BLOCKED", {"target_family": payload.target_family})
            audit(db, case.id, "BACKOFFICE_RECLASSIFICATION_DENIED", {"target_family": payload.target_family}, actor_reviewer_id=principal.actor_id)
            db.commit()
            raise HTTPException(status_code=409, detail="Private family is unavailable")

    with atomic_workflow_transaction(db) as commit:
        entry = FAMILY_MANIFEST[payload.target_family]
        previous_vertical = case.vertical
        invalidate_case_derivatives(
            db,
            case,
            reason="family_reclassification",
            mutation="assisted_reclassification",
            exclude_review_ids=frozenset({review.id}),
        )
        case.family = entry.code
        case.vertical = entry.vertical
        case.title = entry.title
        case.status = "INTAKE"

        _complete_review_row(review, payload.reviewer_decision)
        audit(
            db,
            case.id,
            "HUMAN_REVIEW_RECLASSIFIED_INTAKE",
            {
                "review_id": review.id,
                "from_family": None,
                "from_vertical": previous_vertical,
                "target_family": entry.code,
                "target_vertical": entry.vertical,
            },
            actor_reviewer_id=principal.actor_id,
        )
        db.flush()
        next_question = get_next_question(db, case)
        response = {
            "review_id": review.id,
            "review_status": review.status,
            "case_id": case.id,
            "case_status": case.status,
            "family": case.family,
            "vertical": case.vertical,
            "title": case.title,
            "next_question": next_question,
        }
        commit()
        return response


@router.post("/reviews/{review_id}/escalate-professional")
def escalate_post_response_review_to_professional(
    review_id: str,
    payload: ProfessionalEscalation,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, Any]:
    """Move a post-response dead end into an explicit professional-review handoff.

    This route deliberately does not choose a regulator, ADR body, court, deadline,
    remedy, probability or legal conclusion. It only records that the automated Motor
    must stop and that a professional must decide the next legal route from the dossier.
    """
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    if review.reason != "POST_DENIAL_ESCALATION_REVIEW":
        raise HTTPException(
            status_code=409,
            detail="Only a post-response escalation review can be sent to professional handoff",
        )

    case = lock_case_for_update(db, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="Case is no longer waiting for escalation review")
    if case.mode == "PRIVATE_REAL_BETA":
        raise HTTPException(409, "Use the structured private resolution route")

    _complete_review_row(review, payload.reviewer_decision)
    complete_current_action(db, case, only_types={"HUMAN_REVIEW"})

    professional_review = create_human_review(
        db,
        case,
        reason="PROFESSIONAL_ESCALATION_REQUIRED",
        priority="HIGH",
        context={
            "phase": "PROFESSIONAL_REVIEW",
            "source_review_id": review.id,
            "family": case.family,
            "decision_id": case.current_decision_id,
        },
    )
    db.flush()
    action = set_current_action(
        db,
        case,
        "HUMAN_REVIEW",
        payload={
            "reason": professional_review.reason,
            "review_id": professional_review.id,
            "phase": "PROFESSIONAL_REVIEW",
            "decision_id": case.current_decision_id,
        },
    )
    case.status = "HUMAN_REVIEW"
    audit(
        db,
        case.id,
        "PROFESSIONAL_ESCALATION_REQUIRED",
        {
            "source_review_id": review.id,
            "professional_review_id": professional_review.id,
            "action_id": action.id,
            "family": case.family,
            "decision_id": case.current_decision_id,
        },
        actor_reviewer_id=principal.actor_id,
    )
    db.commit()

    return {
        "review_id": review.id,
        "review_status": review.status,
        "case_id": case.id,
        "case_status": case.status,
        "professional_review_id": professional_review.id,
        "action_id": action.id,
        "phase": "PROFESSIONAL_REVIEW",
    }


@router.post("/reviews/{review_id}/resolve-structured")
def resolve_structured_review(
    review_id: str,
    payload: StructuredReviewResolution,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, Any]:
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    if review.reason == RELEASE_REASON and payload.reason_code != "FACT_CORRECTION_REQUIRED":
        raise HTTPException(status_code=409, detail="Release review fact correction requires its structured reason code")
    if review.reason == "UNSUPPORTED_CLASSIFICATION":
        raise HTTPException(
            status_code=409,
            detail="Unsupported-intake routing reviews must be reclassified before structured fact resolution",
        )

    case = lock_case_for_update(db, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.mode == "PRIVATE_REAL_BETA":
        require_assigned_reviewer(db, review, case, principal.reviewer)
        require_current_version(db, review, case)
        if payload.reason_code != "FACT_CORRECTION_REQUIRED":
            raise HTTPException(422, "Structured reason code required")
    elif payload.reviewer_decision is None:
        raise HTTPException(422, "Reviewer decision required for synthetic review")
    if (case.family or "") not in EVALUATORS:
        raise HTTPException(
            status_code=409,
            detail="Structured facts cannot close this review until the case is routed to an automated family",
        )

    with atomic_workflow_transaction(db) as commit:
        created_fact_ids: list[str] = []
        update_audit: list[dict[str, str]] = []
        for item in payload.fact_updates:
            validate_private_fact(case, item.key, item.value, state=item.state)
            previous = db.scalars(
                select(Fact)
                .where(Fact.case_id == case.id, Fact.key == item.key)
                .order_by(Fact.created_at.desc())
            ).first()
            fact = Fact(
                case_id=case.id,
                key=item.key,
                value_json={"value": item.value},
                state=item.state,
                materiality=item.materiality,
                confidence=None,
                user_confirmed=False,
                created_by="human",
                supersedes_fact_id=previous.id if previous else None,
            )
            db.add(fact)
            db.flush()
            created_fact_ids.append(fact.id)
            update_audit.append(
                {
                    "fact_id": fact.id,
                    "key": fact.key,
                    "state": fact.state,
                    "materiality": fact.materiality,
                }
            )
            if item.state == "confirmed":
                db.add(
                    Evidence(
                        case_id=case.id,
                        fact_id=fact.id,
                        source_type="human",
                        excerpt=item.note.strip() if item.note else None,
                        strength="strong",
                    )
                )

        if case.mode == "PRIVATE_REAL_BETA":
            previous_action = db.get(Action, case.current_action_id) if case.current_action_id else None
            if previous_action is not None:
                previous_action.status = "SUPERSEDED"
            record_resolution(review, "CORRECT_STRUCTURED_FACTS", payload.reason_code)
        else:
            _complete_review_row(review, payload.reviewer_decision)
        complete_current_action(db, case, only_types={"HUMAN_REVIEW"})
        case.status = "REANALYZING"
        audit(
            db,
            case.id,
            "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
            {
                "review_id": review.id,
                **({"assigned_reviewer_id": review.assigned_reviewer_id}
                   if case.mode == "PRIVATE_REAL_BETA" else {"assigned_to": review.assigned_to}),
                "fact_updates": update_audit,
                "reanalyze_requested": True,
                "review_reason": review.reason,
                **({"reason_code": payload.reason_code, "outcome": "CORRECT_STRUCTURED_FACTS",
                    "decision_id": review.context_json.get("decision_id"),
                    "action_id": review.context_json.get("diagnosis_action_id"),
                    "facts_version": review.context_json.get("facts_version")}
                   if case.mode == "PRIVATE_REAL_BETA" else {}),
            },
            actor_reviewer_id=principal.actor_id,
        )
        db.flush()

        # Reviews created after a company response remain in the response phase even if a
        # person adds verified facts. This keeps the anti-loop guard active across both
        # the first escalation review and the later professional-review handoff.
        if review.reason in _POST_RESPONSE_REVIEW_REASONS:
            case.status = "RESPONSE_RECEIVED"

        result, decision, action = diagnose(db, case)
        response = {
            "review_id": review.id,
            "review_status": "COMPLETED",
            "case_id": case.id,
            "case_status": case.status,
            "fact_ids": created_fact_ids,
            "updated_diagnosis": (
                {"status": "HUMAN_REVIEW", "reason": "Private family review required"}
                if case.mode == "PRIVATE_REAL_BETA" and case.current_decision_id is None
                else result.to_dict()
            ),
            "decision_id": case.current_decision_id,
            "action_id": action.id,
        }
        commit()
        return response
