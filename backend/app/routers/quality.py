from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..case_quality import build_dossier_quality
from ..db import get_db
from ..models import AuditEvent, Case, Communication, Decision, Document, Evidence, Fact, Outcome
from ..reviews import HumanReview
from ..security import require_case_access


router = APIRouter(
    prefix="/api/cases",
    tags=["case-quality"],
    dependencies=[Depends(require_case_access)],
)


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

    inbound = db.scalars(
        select(Communication)
        .where(
            Communication.case_id == case.id,
            Communication.direction == "INBOUND",
        )
        .order_by(Communication.received_at.asc())
    ).all()
    for communication in inbound:
        items.append(
            {
                "direction": "INBOUND",
                "kind": "COMPANY_RESPONSE",
                "channel": communication.channel,
                "reference_number": communication.reference_number,
                "body": communication.body,
                "occurred_on": communication.received_at.date().isoformat()
                if communication.received_at is not None
                else None,
                "recorded_at": communication.received_at,
            }
        )

    items.sort(key=lambda item: item["recorded_at"])
    return {"case_id": case.id, "communications": items}
