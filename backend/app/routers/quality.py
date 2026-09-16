from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..case_quality import build_dossier_quality
from ..db import get_db
from ..models import AuditEvent, Case, Communication, Decision, Document, Evidence, Fact, Outcome
from ..reviews import HumanReview
from ..schemas_v2 import ResponseInput
from ..security import require_case_access
from .cases_v2 import response as process_company_response


router = APIRouter(
    prefix="/api/cases",
    tags=["case-quality"],
    dependencies=[Depends(require_case_access)],
)


class CompanyResponseEvidenceInput(BaseModel):
    text: str = Field(min_length=3, max_length=30000)
    received_on: date | None = None
    channel: str = Field(default="unknown", min_length=2, max_length=30)
    reference_number: str | None = Field(default=None, max_length=100)


@router.get("/{case_id}/quality")
def dossier_quality(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    facts = db.scalars(
        select(Fact).where(Fact.case_id == case.id).order_by(Fact.created_at.asc())
    ).all()
    evidence = db.scalars(
        select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.created_at.asc())
    ).all()
    decisions = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).all()
    reviews = db.scalars(
        select(HumanReview)
        .where(HumanReview.case_id == case.id)
        .order_by(HumanReview.created_at.desc())
    ).all()

    return build_dossier_quality(case, facts, evidence, decisions, reviews)


AUDIT_TIMELINE_LABELS = {
    "CASE_CLAIMED_BY_ACCOUNT": (
        "Expediente guardado",
        "Este expediente quedó asociado a tu cuenta.",
    ),
    "CLAIM_SUBMITTED": (
        "Reclamación enviada",
        "Has indicado que la reclamación ya fue enviada a la empresa.",
    ),
    "CLAIM_ACCEPTED_PENDING_EXECUTION": (
        "Respuesta favorable pendiente de comprobar",
        "La empresa ha aceptado la reclamación, pero el expediente seguirá abierto hasta comprobar que se cumple.",
    ),
}


@router.get("/{case_id}/timeline")
def case_timeline(case_id: str, db: Session = Depends(get_db)):
    """Return a deliberately small user-facing history, not the internal audit log."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    events: list[dict] = [
        {
            "type": "CASE_OPENED",
            "label": "Expediente iniciado",
            "detail": "MECORRESPONDE abrió el expediente y empezó a recopilar los hechos necesarios.",
            "at": case.opened_at,
        }
    ]

    documents = db.scalars(
        select(Document).where(Document.case_id == case.id).order_by(Document.uploaded_at.asc())
    ).all()
    for document in documents:
        events.append(
            {
                "type": "DOCUMENT_ADDED",
                "label": "Documento añadido",
                "detail": "Se incorporó un documento al expediente.",
                "at": document.uploaded_at,
            }
        )

    decisions = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.asc())
    ).all()
    for decision in decisions:
        events.append(
            {
                "type": "DIAGNOSIS_UPDATED",
                "label": "Diagnóstico actualizado",
                "detail": "El Motor volvió a evaluar el expediente con los hechos y reglas disponibles.",
                "at": decision.created_at,
            }
        )

    reviews = db.scalars(
        select(HumanReview).where(HumanReview.case_id == case.id).order_by(HumanReview.created_at.asc())
    ).all()
    for review in reviews:
        events.append(
            {
                "type": "HUMAN_REVIEW_REQUESTED",
                "label": "Revisión humana solicitada",
                "detail": "El expediente se detuvo para que una persona revise un punto que no debe resolverse automáticamente.",
                "at": review.created_at,
            }
        )
        if review.completed_at is not None:
            events.append(
                {
                    "type": "HUMAN_REVIEW_COMPLETED",
                    "label": "Revisión humana completada",
                    "detail": "La revisión aportó información al expediente y el Motor puede volver a evaluarlo.",
                    "at": review.completed_at,
                }
            )

    audits = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type.in_(tuple(AUDIT_TIMELINE_LABELS)),
        )
        .order_by(AuditEvent.created_at.asc())
    ).all()
    for audit in audits:
        label, detail = AUDIT_TIMELINE_LABELS[audit.event_type]
        events.append(
            {
                "type": audit.event_type,
                "label": label,
                "detail": detail,
                "at": audit.created_at,
            }
        )

    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case.id))
    if outcome and outcome.verified_by_user and outcome.resolved_at is not None:
        events.append(
            {
                "type": "RESOLUTION_VERIFIED",
                "label": "Resolución comprobada",
                "detail": "Has confirmado que el resultado se ha cumplido y el expediente puede considerarse resuelto.",
                "at": outcome.resolved_at,
            }
        )

    events.sort(key=lambda item: item["at"])
    return {
        "case_id": case.id,
        "current_status": case.status,
        "events": events,
    }


@router.post("/{case_id}/responses/evidenced")
def evidenced_company_response(
    case_id: str,
    payload: CompanyResponseEvidenceInput,
    db: Session = Depends(get_db),
):
    """Analyze a response and attach user-confirmed communication metadata.

    The existing response-analysis path records when MECORRESPONDE processed the text.
    That processing timestamp is not treated as the date the company actually replied.
    The user's calendar date, channel and reference are preserved separately in an audit
    event linked to the exact inbound Communication row, so no hour/minute is fabricated.
    """
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    existing_ids = set(
        db.scalars(
            select(Communication.id).where(
                Communication.case_id == case.id,
                Communication.direction == "INBOUND",
            )
        ).all()
    )

    result = process_company_response(
        case_id,
        ResponseInput(text=payload.text),
        db,
    )

    inbound = db.scalars(
        select(Communication)
        .where(
            Communication.case_id == case.id,
            Communication.direction == "INBOUND",
        )
        .order_by(Communication.received_at.desc())
    ).all()
    communication = next((row for row in inbound if row.id not in existing_ids), None)
    if communication is None:
        raise HTTPException(status_code=500, detail="Analyzed response communication could not be linked")

    communication.channel = payload.channel
    communication.reference_number = payload.reference_number
    db.add(
        AuditEvent(
            case_id=case.id,
            event_type="COMPANY_RESPONSE_RECORDED",
            payload_json={
                "communication_id": communication.id,
                "received_on": payload.received_on.isoformat() if payload.received_on else None,
                "channel": payload.channel,
                "reference": payload.reference_number,
            },
        )
    )
    db.commit()
    return result


@router.get("/{case_id}/communications")
def case_communications(case_id: str, db: Session = Depends(get_db)):
    """Return user-facing communication history without exposing internal audit payloads."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    items: list[dict] = []

    # Outbound submission dates are user-supplied calendar dates. They remain in
    # the audited submission event so MECORRESPONDE never fabricates a time of day.
    submissions = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
        .order_by(AuditEvent.created_at.asc())
    ).all()
    for event in submissions:
        payload = event.payload_json or {}
        items.append(
            {
                "direction": "OUTBOUND",
                "kind": "CLAIM_SUBMISSION",
                "channel": payload.get("channel"),
                "reference_number": payload.get("reference"),
                "body": None,
                "occurred_on": payload.get("submitted_on"),
                "recorded_at": event.created_at,
            }
        )

    response_events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "COMPANY_RESPONSE_RECORDED",
        )
        .order_by(AuditEvent.created_at.asc())
    ).all()
    response_metadata = {
        (event.payload_json or {}).get("communication_id"): event
        for event in response_events
        if (event.payload_json or {}).get("communication_id")
    }

    inbound = db.scalars(
        select(Communication)
        .where(
            Communication.case_id == case.id,
            Communication.direction == "INBOUND",
        )
        .order_by(Communication.received_at.asc())
    ).all()
    for communication in inbound:
        metadata_event = response_metadata.get(communication.id)
        metadata = (metadata_event.payload_json or {}) if metadata_event else {}
        items.append(
            {
                "direction": "INBOUND",
                "kind": "COMPANY_RESPONSE",
                "channel": metadata.get("channel") if metadata_event else None,
                "reference_number": metadata.get("reference") if metadata_event else None,
                "body": communication.body,
                "occurred_on": metadata.get("received_on") if metadata_event else None,
                "recorded_at": metadata_event.created_at if metadata_event else communication.received_at,
            }
        )

    items.sort(key=lambda item: item["recorded_at"])
    return {"case_id": case.id, "communications": items}