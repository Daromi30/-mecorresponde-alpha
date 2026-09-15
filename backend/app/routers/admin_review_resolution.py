from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..db import get_db
from ..models import Case, Evidence, Fact
from ..reviews import HumanReview
from ..services_v2 import EVALUATORS, audit, diagnose


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


def _review_or_404(db: Session, review_id: str) -> HumanReview:
    review = db.get(HumanReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.post("/reviews/{review_id}/resolve-structured")
def resolve_structured_review(
    review_id: str,
    payload: StructuredReviewResolution,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")

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
        },
    )
    db.flush()

    updated_diagnosis = None
    decision_id = None
    action_id = None
    if payload.reanalyze and (case.family or "") in EVALUATORS:
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
