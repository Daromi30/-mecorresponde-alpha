from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..case_lifecycle import complete_current_action, set_current_action
from ..db import get_db
from ..evidence_context import atomic_workflow_transaction
from ..family_manifest import FAMILY_MANIFEST
from ..models import Case, Evidence, Fact
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

    reviewer_decision: str = Field(min_length=3, max_length=10000)
    fact_updates: list[HumanFactUpdate] = Field(min_length=1, max_length=25)
    # Structured human review changes facts; the legal conclusion must therefore be
    # regenerated immediately by the deterministic Motor. There is no supported dormant
    # REANALYZING queue, so accepting False would create an operational dead end.
    reanalyze: Literal[True] = True

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


def _review_or_404(db: Session, review_id: str) -> HumanReview:
    review = db.get(HumanReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def _complete_review_row(review: HumanReview, reviewer_decision: str) -> None:
    review.status = "COMPLETED"
    review.reviewer_decision = reviewer_decision.strip()
    review.completed_at = datetime.now(timezone.utc)


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

    case = db.get(Case, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.family is not None:
        raise HTTPException(status_code=409, detail="Case is already assigned to a resolution family")
    if case.status != "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="Case is no longer waiting for assisted classification")

    with atomic_workflow_transaction(db) as commit:
        entry = FAMILY_MANIFEST[payload.target_family]
        previous_vertical = case.vertical
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

    case = db.get(Case, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.status != "HUMAN_REVIEW":
        raise HTTPException(status_code=409, detail="Case is no longer waiting for escalation review")

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
) -> dict[str, Any]:
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    if review.reason == "UNSUPPORTED_CLASSIFICATION":
        raise HTTPException(
            status_code=409,
            detail="Unsupported-intake routing reviews must be reclassified before structured fact resolution",
        )

    case = db.get(Case, review.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if (case.family or "") not in EVALUATORS:
        raise HTTPException(
            status_code=409,
            detail="Structured facts cannot close this review until the case is routed to an automated family",
        )

    with atomic_workflow_transaction(db) as commit:
        created_fact_ids: list[str] = []
        update_audit: list[dict[str, str]] = []
        for item in payload.fact_updates:
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

        _complete_review_row(review, payload.reviewer_decision)
        complete_current_action(db, case, only_types={"HUMAN_REVIEW"})
        case.status = "REANALYZING"
        audit(
            db,
            case.id,
            "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
            {
                "review_id": review.id,
                "assigned_to": review.assigned_to,
                "fact_updates": update_audit,
                "reanalyze_requested": True,
                "review_reason": review.reason,
            },
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
            "updated_diagnosis": result.to_dict(),
            "decision_id": decision.id,
            "action_id": action.id,
        }
        commit()
        return response
