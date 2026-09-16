from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..db import get_db
from ..family_manifest import FAMILY_MANIFEST
from ..models import Case, Evidence, Fact
from ..reviews import HumanReview
from ..services_v2 import EVALUATORS, audit, diagnose, get_next_question


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
    reanalyze: bool = True

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


def _review_or_404(db: Session, review_id: str) -> HumanReview:
    review = db.get(HumanReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


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

    entry = FAMILY_MANIFEST[payload.target_family]
    previous_vertical = case.vertical
    case.family = entry.code
    case.vertical = entry.vertical
    case.title = entry.title
    case.status = "INTAKE"

    review.status = "COMPLETED"
    review.reviewer_decision = payload.reviewer_decision.strip()
    review.completed_at = datetime.now(timezone.utc)
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
    db.commit()
    db.refresh(case)

    return {
        "review_id": review.id,
        "review_status": review.status,
        "case_id": case.id,
        "case_status": case.status,
        "family": case.family,
        "vertical": case.vertical,
        "title": case.title,
        "next_question": get_next_question(db, case),
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

    review.status = "COMPLETED"
    review.reviewer_decision = payload.reviewer_decision.strip()
    review.completed_at = datetime.now(timezone.utc)
    case.status = "REANALYZING"
    audit(
        db,
        case.id,
        "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
        {
            "review_id": review.id,
            "assigned_to": review.assigned_to,
            "fact_updates": update_audit,
            "reanalyze_requested": payload.reanalyze,
            "review_reason": review.reason,
        },
    )
    db.flush()

    updated_diagnosis = None
    decision_id = None
    action_id = None
    if payload.reanalyze and (case.family or "") in EVALUATORS:
        # A structured resolution after a company denial/partial response is still part
        # of the response phase. Preserve that phase marker so the global diagnostic
        # guard can never turn a reviewer-added fact into a second initial claim. If the
        # deterministic result still proposes the original outbound action, the Motor
        # opens a fresh protected escalation review instead.
        if review.reason == "POST_DENIAL_ESCALATION_REVIEW":
            case.status = "RESPONSE_RECEIVED"
        try:
            result, decision, action = diagnose(db, case)
        except Exception:
            db.rollback()
            raise
        updated_diagnosis = result.to_dict()
        decision_id = decision.id
        action_id = action.id
    else:
        db.commit()

    return {
        "review_id": review.id,
        "review_status": "COMPLETED",
        "case_id": case.id,
        "case_status": case.status,
        "fact_ids": created_fact_ids,
        "updated_diagnosis": updated_diagnosis,
        "decision_id": decision_id,
        "action_id": action_id,
    }
