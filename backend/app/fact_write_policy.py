from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Action, Case, Evidence, Fact


_INSTALLED = False


def install_fact_write_policy() -> None:
    """Keep fact provenance and workflow lifecycle aligned.

    Claimant answers legitimately reopen the intake/diagnosis phase. Any decision or action
    produced from the previous fact snapshot is therefore superseded and must stop being
    current. Facts derived from a company response or protected human review are evidence
    inside an already-advanced phase and must not turn the case back into INTAKE.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_upsert_fact = svc.upsert_fact

    def upsert_fact_with_source_aware_lifecycle(
        db: Session,
        case: Case,
        key: str,
        value: Any,
        state: str = "asserted",
        materiality: str = "critical",
        confidence: float | None = None,
        user_confirmed: bool = True,
        created_by: str = "user",
    ) -> Fact:
        if created_by == "user":
            previous_action_id = case.current_action_id
            previous_decision_id = case.current_decision_id
            current = db.get(Action, previous_action_id) if previous_action_id else None
            if current is not None and current.case_id == case.id and current.status != "COMPLETED":
                current.status = "SUPERSEDED"
                current.completed_at = datetime.now(timezone.utc)
            if previous_action_id or previous_decision_id:
                svc.audit(
                    db,
                    case.id,
                    "CURRENT_ANALYSIS_SUPERSEDED",
                    {
                        "fact_key": key,
                        "previous_action_id": previous_action_id,
                        "previous_decision_id": previous_decision_id,
                    },
                )
            case.current_action_id = None
            case.current_decision_id = None
            return previous_upsert_fact(
                db,
                case,
                key,
                value,
                state=state,
                materiality=materiality,
                confidence=confidence,
                user_confirmed=user_confirmed,
                created_by=created_by,
            )

        previous = db.scalars(
            select(Fact)
            .where(Fact.case_id == case.id, Fact.key == key)
            .order_by(Fact.created_at.desc())
        ).first()
        fact = Fact(
            case_id=case.id,
            key=key,
            value_json={"value": value},
            state=state,
            materiality=materiality,
            confidence=confidence,
            user_confirmed=user_confirmed,
            created_by=created_by,
            supersedes_fact_id=previous.id if previous else None,
        )
        db.add(fact)
        db.flush()
        if created_by in {"company", "human"}:
            db.add(
                Evidence(
                    case_id=case.id,
                    fact_id=fact.id,
                    source_type=created_by,
                    strength="strong" if user_confirmed or created_by == "human" else "medium",
                )
            )
        svc.audit(
            db,
            case.id,
            "FACT_RECORDED",
            {
                "fact_id": fact.id,
                "key": key,
                "state": state,
                "source": created_by,
                "supersedes": previous.id if previous else None,
            },
        )
        # Do not alter case.status here. The response/review workflow owns the lifecycle.
        db.commit()
        db.refresh(fact)
        return fact

    svc.upsert_fact = upsert_fact_with_source_aware_lifecycle
    _INSTALLED = True
