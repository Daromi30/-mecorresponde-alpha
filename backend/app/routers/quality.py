from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calendar_clock import spain_today
from ..case_quality import build_dossier_quality
from ..db import get_db
from ..evidence_context import company_response_evidence_context, outcome_evidence_context
from ..models import Action, AuditEvent, Case, Communication, Decision, Document, Evidence, Fact, Outcome
from ..reviews import HumanReview
from ..schemas_v2 import OutcomeInput, ResponseInput
from ..security import require_case_access
from .cases_v2 import outcome as process_outcome
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


class OutcomeEvidenceInput(BaseModel):
    result_type: Literal["FAVORABLE"] = "FAVORABLE"
    amount_recovered: float | None = Field(default=None, ge=0)
    verified_by_user: bool = False
    resolved_on: date | None = None
    non_monetary_result: str | None = Field(default=None, max_length=2000)
    resolution_channel: str | None = Field(default=None, max_length=80)


def _audit_calendar_date(db: Session, case_id: str, event_type: str, field: str) -> date | None:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.case_id == case_id, AuditEvent.event_type == event_type)
        .order_by(AuditEvent.created_at.desc())
    ).all()
    for event in events:
        raw = (event.payload_json or {}).get(field)
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            continue
    return None


def _require_waiting_for_company_response(db: Session, case: Case) -> None:
    current = db.get(Action, case.current_action_id) if case.current_action_id else None
    submitted = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    )
    if (
        not submitted
        or case.status != "WAITING_RESPONSE"
        or current is None
        or current.case_id != case.id
        or current.type != "WAIT_FOR_RESPONSE"
        or current.status != "OPEN"
    ):
        raise HTTPException(
            status_code=409,
            detail="A company response can only be recorded while this case is waiting for a submitted claim response",
        )


def _require_pending_execution_verification(db: Session, case: Case) -> None:
    current = db.get(Action, case.current_action_id) if case.current_action_id else None
    if (
        case.status != "RESOLVED_PENDING_EXECUTION"
        or current is None
        or current.case_id != case.id
        or current.type != "VERIFY_EXECUTION"
        or current.status != "OPEN"
    ):
        raise HTTPException(
            status_code=409,
            detail="An outcome can only be recorded after a favorable response is awaiting execution verification",
        )


def _validate_response_chronology(db: Session, case: Case, received_on: date | None) -> None:
    if received_on is None:
        return
    if received_on > spain_today():
        raise HTTPException(
            status_code=422,
            detail="The company response date cannot be in the future",
        )
    submitted_on = _audit_calendar_date(db, case.id, "CLAIM_SUBMITTED", "submitted_on")
    if submitted_on and received_on < submitted_on:
        raise HTTPException(
            status_code=422,
            detail="The company response date cannot be earlier than the recorded claim submission date",
        )


def _validate_outcome_evidence(db: Session, case: Case, payload: OutcomeEvidenceInput) -> None:
    if payload.verified_by_user:
        if not (payload.resolution_channel or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Verified outcomes must record how the result was fulfilled",
            )
        recovered = float(payload.amount_recovered or 0)
        if recovered <= 0 and len((payload.non_monetary_result or "").strip()) < 3:
            raise HTTPException(
                status_code=422,
                detail="Verified non-monetary outcomes must describe what was fulfilled",
            )
    elif payload.resolved_on is not None:
        raise HTTPException(
            status_code=422,
            detail="An execution date cannot be confirmed while the outcome is still unverified",
        )

    if payload.resolved_on is None:
        return
    if payload.resolved_on > spain_today():
        raise HTTPException(
            status_code=422,
            detail="The recorded fulfillment date cannot be in the future",
        )
    response_on = _audit_calendar_date(db, case.id, "COMPANY_RESPONSE_RECORDED", "received_on")
    submitted_on = _audit_calendar_date(db, case.id, "CLAIM_SUBMITTED", "submitted_on")
    lower_bound = response_on or submitted_on
    if lower_bound and payload.resolved_on < lower_bound:
        raise HTTPException(
            status_code=422,
            detail="The recorded fulfillment date cannot be earlier than the verified case chronology",
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
                "resolved_on": outcome.resolved_on,
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
    """Analyze a response with its user-confirmed communication metadata in one transaction."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    _require_waiting_for_company_response(db, case)
    _validate_response_chronology(db, case, payload.received_on)

    with company_response_evidence_context(
        received_on=payload.received_on,
        channel=payload.channel,
        reference_number=payload.reference_number,
    ):
        return process_company_response(
            case_id,
            ResponseInput(text=payload.text),
            db,
        )


@router.post("/{case_id}/outcome/evidenced")
def evidenced_outcome(
    case_id: str,
    payload: OutcomeEvidenceInput,
    db: Session = Depends(get_db),
):
    """Persist outcome state and user-confirmed execution evidence in one transaction."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    _require_pending_execution_verification(db, case)
    _validate_outcome_evidence(db, case, payload)

    with outcome_evidence_context(
        resolved_on=payload.resolved_on,
        non_monetary_result=payload.non_monetary_result,
        resolution_channel=payload.resolution_channel,
    ):
        result = process_outcome(
            case_id,
            OutcomeInput(
                result_type="FAVORABLE",
                amount_recovered=payload.amount_recovered,
                verified_by_user=payload.verified_by_user,
            ),
            db,
        )

    return {
        **result,
        "resolved_on": payload.resolved_on.isoformat() if payload.resolved_on else None,
        "resolution_channel": payload.resolution_channel,
        "non_monetary_result": payload.non_monetary_result,
    }


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("/{case_id}/communications")
def case_communications(case_id: str, db: Session = Depends(get_db)):
    """Return user-facing history from normalized communications with audit fallback."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    items: list[dict] = []

    submissions = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
        .order_by(AuditEvent.created_at.asc())
    ).all()
    outbound_rows = db.scalars(
        select(Communication).where(
            Communication.case_id == case.id,
            Communication.direction == "OUTBOUND",
        )
    ).all()
    for event in submissions:
        payload = event.payload_json or {}
        matches = [
            row
            for row in outbound_rows
            if row.channel == payload.get("channel")
            and row.reference_number == payload.get("reference")
        ]
        communication = matches[0] if len(matches) == 1 else (
            outbound_rows[0] if len(outbound_rows) == 1 and len(submissions) == 1 else None
        )
        items.append(
            {
                "direction": "OUTBOUND",
                "kind": "CLAIM_SUBMISSION",
                "channel": communication.channel if communication is not None else payload.get("channel"),
                "reference_number": (
                    communication.reference_number if communication is not None else payload.get("reference")
                ),
                "body": communication.body if communication is not None else None,
                "occurred_on": (
                    _iso_date(communication.occurred_on)
                    if communication is not None and communication.occurred_on is not None
                    else payload.get("submitted_on")
                ),
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
                "channel": communication.channel or metadata.get("channel"),
                "reference_number": communication.reference_number or metadata.get("reference"),
                "body": communication.body,
                "occurred_on": (
                    _iso_date(communication.occurred_on)
                    if communication.occurred_on is not None
                    else metadata.get("received_on")
                ),
                "recorded_at": metadata_event.created_at if metadata_event else communication.received_at,
            }
        )

    items.sort(key=lambda item: item["recorded_at"])
    return {"case_id": case.id, "communications": items}
