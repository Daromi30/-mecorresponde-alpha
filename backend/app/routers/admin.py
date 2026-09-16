from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..case_handoff import build_case_handoff
from ..db import get_db
from ..models import (
    AuditEvent,
    Case,
    Communication,
    Decision,
    Document,
    Outcome,
)
from ..reviews import HumanReview
from ..routers.cases_v2 import serialize_case
from ..services_v2 import audit


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class ReviewAssignment(BaseModel):
    assigned_to: str = Field(min_length=1, max_length=120)


class ReviewCompletion(BaseModel):
    reviewer_decision: str = Field(min_length=1, max_length=10000)


def _case_or_404(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _review_or_404(db: Session, review_id: str) -> HumanReview:
    review = db.get(HumanReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def _distinct_cases_for_event(db: Session, event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(AuditEvent.case_id))).where(
                AuditEvent.event_type == event_type,
                AuditEvent.case_id.is_not(None),
            )
        )
        or 0
    )


@router.get("/health")
def admin_health() -> dict[str, str]:
    return {"status": "ok", "surface": "backoffice"}


@router.get("/stats")
def admin_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    open_reviews = db.scalar(
        select(func.count()).select_from(HumanReview).where(HumanReview.status == "OPEN")
    ) or 0
    total_cases = db.scalar(select(func.count()).select_from(Case)) or 0
    human_review_cases = db.scalar(
        select(func.count()).select_from(Case).where(Case.status == "HUMAN_REVIEW")
    ) or 0
    ready_to_submit = db.scalar(
        select(func.count()).select_from(Case).where(Case.status == "READY_TO_SUBMIT")
    ) or 0
    waiting_response = db.scalar(
        select(func.count()).select_from(Case).where(Case.status == "WAITING_RESPONSE")
    ) or 0
    needs_information = db.scalar(
        select(func.count()).select_from(Case).where(Case.status == "NEEDS_INFORMATION")
    ) or 0
    verified_resolutions = db.scalar(
        select(func.count()).select_from(Outcome).where(Outcome.verified_by_user.is_(True))
    ) or 0
    total_recovered = db.scalar(
        select(func.coalesce(func.sum(Outcome.amount_recovered), 0.0)).where(
            Outcome.verified_by_user.is_(True)
        )
    ) or 0.0

    family_rows = db.execute(
        select(Case.family, func.count(Case.id))
        .group_by(Case.family)
        .order_by(func.count(Case.id).desc())
    ).all()
    vertical_rows = db.execute(
        select(Case.vertical, func.count(Case.id))
        .group_by(Case.vertical)
        .order_by(func.count(Case.id).desc())
    ).all()
    status_rows = db.execute(
        select(Case.status, func.count(Case.id))
        .group_by(Case.status)
        .order_by(func.count(Case.id).desc())
    ).all()

    funnel = {
        "started": int(total_cases),
        "diagnosed": _distinct_cases_for_event(db, "DIAGNOSIS_GENERATED"),
        "action_prepared": _distinct_cases_for_event(db, "CLAIM_PACKAGE_PREPARED"),
        "submitted": _distinct_cases_for_event(db, "CLAIM_SUBMITTED"),
        "response_analyzed": _distinct_cases_for_event(db, "RESPONSE_ANALYZED"),
        "resolved_verified": int(verified_resolutions),
    }

    return {
        "total_cases": int(total_cases),
        "open_reviews": int(open_reviews),
        "human_review_cases": int(human_review_cases),
        "ready_to_submit": int(ready_to_submit),
        "waiting_response": int(waiting_response),
        "needs_information": int(needs_information),
        "verified_resolutions": int(verified_resolutions),
        "total_recovered": round(float(total_recovered), 2),
        "funnel": funnel,
        "cases_by_vertical": {
            str(key or "UNCLASSIFIED"): int(count) for key, count in vertical_rows
        },
        "cases_by_family": {
            str(key or "UNCLASSIFIED"): int(count) for key, count in family_rows
        },
        "cases_by_status": {str(key): int(count) for key, count in status_rows},
    }


@router.get("/reviews")
def review_queue(
    status: str = "OPEN",
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    stmt = (
        select(HumanReview)
        .where(HumanReview.status == status)
        .order_by(HumanReview.priority.desc(), HumanReview.created_at.asc())
        .limit(limit)
    )
    rows = db.scalars(stmt).all()
    result: list[dict[str, Any]] = []
    for review in rows:
        case = db.get(Case, review.case_id)
        decision = None
        if case:
            decision = db.scalars(
                select(Decision)
                .where(Decision.case_id == case.id)
                .order_by(Decision.created_at.desc())
            ).first()
        result.append(
            {
                "id": review.id,
                "case_id": review.case_id,
                "reason": review.reason,
                "priority": review.priority,
                "status": review.status,
                "assigned_to": review.assigned_to,
                "created_at": review.created_at,
                "case": None
                if case is None
                else {
                    "status": case.status,
                    "family": case.family,
                    "vertical": case.vertical,
                    "title": case.title,
                    "opened_at": case.opened_at,
                    "viability": decision.viability if decision else None,
                    "claimable_amount": decision.claimable_amount if decision else None,
                    "economic_value": decision.economic_value if decision else None,
                },
            }
        )
    return result


@router.get("/cases/{case_id}")
def case_detail(case_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    case = _case_or_404(db, case_id)
    documents = db.scalars(
        select(Document).where(Document.case_id == case.id).order_by(Document.uploaded_at.asc())
    ).all()
    communications = db.scalars(
        select(Communication)
        .where(Communication.case_id == case.id)
        .order_by(Communication.received_at.asc(), Communication.sent_at.asc())
    ).all()
    audit_rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.case_id == case.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(200)
    ).all()
    outcome = db.scalars(select(Outcome).where(Outcome.case_id == case.id)).first()

    return {
        **serialize_case(db, case),
        "documents": [
            {
                "id": doc.id,
                "filename": doc.original_filename,
                "mime_type": doc.mime_type,
                "sha256": doc.sha256,
                "document_type": doc.document_type,
                "processing_status": doc.processing_status,
                "page_count": doc.page_count,
                "uploaded_at": doc.uploaded_at,
            }
            for doc in documents
        ],
        "communications": [
            {
                "id": item.id,
                "direction": item.direction,
                "channel": item.channel,
                "body": item.body,
                "sent_at": item.sent_at,
                "received_at": item.received_at,
                "reference_number": item.reference_number,
                "document_id": item.document_id,
            }
            for item in communications
        ],
        "audit": [
            {
                "id": item.id,
                "event_type": item.event_type,
                "payload": item.payload_json,
                "created_at": item.created_at,
            }
            for item in audit_rows
        ],
        "outcome": None
        if outcome is None
        else {
            "result_type": outcome.result_type,
            "amount_requested": outcome.amount_requested,
            "amount_recovered": outcome.amount_recovered,
            "verified_by_user": outcome.verified_by_user,
            "resolved_at": outcome.resolved_at,
            "failure_reason": outcome.failure_reason,
        },
    }


@router.get("/cases/{case_id}/handoff")
def admin_case_handoff(case_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    case = _case_or_404(db, case_id)
    return build_case_handoff(db, case)


@router.post("/reviews/{review_id}/assign")
def assign_review(
    review_id: str,
    payload: ReviewAssignment,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    review = _review_or_404(db, review_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    review.assigned_to = payload.assigned_to.strip()
    audit(
        db,
        review.case_id,
        "HUMAN_REVIEW_ASSIGNED",
        {"review_id": review.id, "assigned_to": review.assigned_to},
    )
    db.commit()
    return {
        "review_id": review.id,
        "status": review.status,
        "assigned_to": review.assigned_to,
    }


@router.post("/reviews/{review_id}/complete")
def complete_review(
    review_id: str,
    payload: ReviewCompletion,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reject unstructured review completion.

    A free-text reviewer note is useful context, but it must never advance the Resolution
    Engine by itself. Review completion must use one of the explicit, traceable routes:
    structured facts plus deterministic reanalysis, assisted family reclassification, or
    professional escalation. Keeping this legacy endpoint fail-closed also protects older
    clients that may still try to call it.
    """
    review = _review_or_404(db, review_id)
    _case_or_404(db, review.case_id)
    if review.status != "OPEN":
        raise HTTPException(status_code=409, detail="Review is not open")
    raise HTTPException(
        status_code=409,
        detail=(
            "Human reviews cannot be closed with a generic note; use structured fact resolution, "
            "assisted reclassification, or the explicit professional-review workflow"
        ),
    )
