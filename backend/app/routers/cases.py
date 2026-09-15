from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..engine.deadlines import add_business_days
from ..models import Action, Case, Deadline, Decision, Document, Evidence, Fact, HumanReview, Outcome
from ..schemas import (
    CaseCreate, ChargesInput, DocumentFactConfirm, FactUpsert,
    OutcomeInput, ResponseInput, SubmissionInput,
)
from ..services import (
    analyze_company_response, audit, confirm_document_fact, create_case, diagnose,
    get_next_question, prepare_claim_package, save_upload, upsert_fact,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])


def case_or_404(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def serialize_case(db: Session, case: Case):
    facts = db.scalars(select(Fact).where(Fact.case_id == case.id).order_by(Fact.created_at.asc())).all()
    evidence = db.scalars(select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.created_at.asc())).all()
    decisions = db.scalars(select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())).all()
    actions = db.scalars(select(Action).where(Action.case_id == case.id).order_by(Action.id.desc())).all()
    deadlines = db.scalars(select(Deadline).where(Deadline.case_id == case.id)).all()
    reviews = db.scalars(select(HumanReview).where(HumanReview.case_id == case.id).order_by(HumanReview.created_at.desc())).all()
    return {
        "id": case.id,
        "status": case.status,
        "vertical": case.vertical,
        "family": case.family,
        "title": case.title,
        "raw_intake": case.raw_intake,
        "current_decision_id": case.current_decision_id,
        "current_action_id": case.current_action_id,
        "opened_at": case.opened_at,
        "facts": [
            {
                "id": f.id, "key": f.key, "value": f.value_json.get("value"),
                "state": f.state, "user_confirmed": f.user_confirmed,
                "created_by": f.created_by, "supersedes_fact_id": f.supersedes_fact_id,
            }
            for f in facts
        ],
        "evidence": [
            {
                "id": e.id, "fact_id": e.fact_id, "document_id": e.document_id,
                "source_type": e.source_type, "locator": e.locator,
                "excerpt": e.excerpt, "strength": e.strength,
            }
            for e in evidence
        ],
        "decisions": [
            {
                "id": d.id, "viability": d.viability, "scope_status": d.scope_status,
                "economic_value": d.economic_value, "claimable_amount": d.claimable_amount,
                "worth_pursuing": d.worth_pursuing,
                "reasoning_summary": d.reasoning_summary,
                "counterarguments": d.counterarguments_snapshot,
                "rule_evaluations": d.rule_evaluations_json,
                "created_at": d.created_at,
            }
            for d in decisions
        ],
        "actions": [
            {"id": a.id, "type": a.type, "status": a.status, "payload": a.payload_json}
            for a in actions
        ],
        "deadlines": [
            {"id": x.id, "type": x.deadline_type, "computed_date": x.computed_date, "status": x.status}
            for x in deadlines
        ],
        "reviews": [
            {"id": r.id, "reason": r.reason, "priority": r.priority, "status": r.status, "created_at": r.created_at}
            for r in reviews
        ],
    }


@router.post("")
def create(payload: CaseCreate, db: Session = Depends(get_db)):
    case = create_case(db, payload.message)
    return {**serialize_case(db, case), "next_question": get_next_question(db, case)}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    return serialize_case(db, case_or_404(db, case_id))


@router.get("/{case_id}/next-question")
def question(case_id: str, db: Session = Depends(get_db)):
    return get_next_question(db, case_or_404(db, case_id))


@router.get("/{case_id}/reviews")
def reviews(case_id: str, db: Session = Depends(get_db)):
    case_or_404(db, case_id)
    rows = db.scalars(
        select(HumanReview).where(HumanReview.case_id == case_id).order_by(HumanReview.created_at.desc())
    ).all()
    return [
        {"id": r.id, "reason": r.reason, "priority": r.priority, "status": r.status, "created_at": r.created_at}
        for r in rows
    ]


@router.post("/{case_id}/facts")
def fact(case_id: str, payload: FactUpsert, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    value = payload.value
    if payload.key.endswith("_date") and isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            raise HTTPException(422, "Use YYYY-MM-DD")
    created = upsert_fact(
        db, case, payload.key, value, payload.state, payload.materiality,
        payload.confidence, payload.user_confirmed,
    )
    return {"fact_id": created.id, "next_question": get_next_question(db, case)}


@router.post("/{case_id}/charges")
def charges(case_id: str, payload: ChargesInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    key_by_family = {
        "E04-A": "electricity.addon.charges",
        "E04-B": "electricity.addon.charges",
        "E02-B": "electricity.billing.duplicate_charges",
    }
    key = key_by_family.get(case.family)
    if not key:
        raise HTTPException(422, "Este tipo de caso no usa el endpoint de cargos")
    values = [x.model_dump(mode="json") for x in payload.charges]
    created = upsert_fact(db, case, key, values, state="confirmed", user_confirmed=True)
    return {"fact_id": created.id, "next_question": get_next_question(db, case)}


@router.post("/{case_id}/documents")
async def documents(case_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Max 15 MB in internal alpha")
    doc, ext = save_upload(
        db, case, file.filename or "upload",
        file.content_type or "application/octet-stream", data,
    )
    return {
        "document_id": doc.id, "status": doc.processing_status,
        "extracted": ext.structured_json, "quality_flags": ext.quality_flags,
    }


@router.post("/{case_id}/documents/{document_id}/confirm-fact")
def document_fact(
    case_id: str, document_id: str, payload: DocumentFactConfirm,
    db: Session = Depends(get_db),
):
    case = case_or_404(db, case_id)
    document = db.get(Document, document_id)
    if not document or document.case_id != case.id:
        raise HTTPException(404, "Document not found")
    created = confirm_document_fact(
        db, case, document, payload.key, payload.value,
        locator=payload.locator, excerpt=payload.excerpt,
    )
    return {"fact_id": created.id, "next_question": get_next_question(db, case)}


@router.post("/{case_id}/diagnose")
def run_diagnosis(case_id: str, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    try:
        result, decision, action = diagnose(db, case)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {**result.to_dict(), "decision_id": decision.id, "action_id": action.id}


@router.post("/{case_id}/prepare-claim")
def prepare_claim(case_id: str, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    try:
        return prepare_claim_package(db, case)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/{case_id}/submission")
def submission(case_id: str, payload: SubmissionInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    case.status = "WAITING_RESPONSE"
    audit(db, case.id, "CLAIM_SUBMITTED", {
        "submitted_on": str(payload.submitted_on), "reference": payload.reference_number,
        "channel": payload.channel,
    })
    if case.vertical != "electricity":
        db.commit()
        return {
            "status": case.status,
            "deadline": None,
            "deadline_status": "NOT_CONFIGURED",
            "warning": "No se inventa un plazo sectorial para esta familia; el seguimiento se configurará con su regla aplicable.",
        }
    holiday_set: set[date] = set()
    if settings.legal_holidays_csv:
        for raw in settings.legal_holidays_csv.split(","):
            if raw.strip():
                holiday_set.add(date.fromisoformat(raw.strip()))
    target = add_business_days(payload.submitted_on, 15, holiday_set)
    status = "ACTIVE" if settings.legal_holidays_csv else "PROVISIONAL_CALENDAR"
    db.add(Deadline(
        case_id=case.id,
        deadline_type="ELECTRICITY_COMPLAINT_RESPONSE",
        trigger_event="VERIFIED_INITIAL_CLAIM_SUBMISSION",
        trigger_date=payload.submitted_on,
        computed_date=target,
        status=status,
    ))
    db.commit()
    return {
        "status": case.status, "deadline": target, "deadline_status": status,
        "warning": None if status == "ACTIVE" else "El calendario es provisional hasta configurar festivos oficiales aplicables.",
    }


@router.post("/{case_id}/responses")
def response(case_id: str, payload: ResponseInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    result = analyze_company_response(db, case, payload.text)
    if result["type"] == "UNKNOWN":
        review = HumanReview(
            case_id=case.id, reason="UNRECOGNIZED_COMPANY_RESPONSE",
            priority="HIGH", status="OPEN",
        )
        db.add(review)
        db.flush()
        action = Action(
            case_id=case.id, type="HUMAN_REVIEW", status="OPEN",
            payload_json={"reason": review.reason, "review_id": review.id},
        )
        db.add(action)
        db.flush()
        case.current_action_id = action.id
        case.status = "HUMAN_REVIEW"
        audit(db, case.id, "HUMAN_REVIEW_QUEUED", {"review_id": review.id, "reason": review.reason})
        db.commit()
        return {"analysis": result, "case_status": case.status, "updated_diagnosis": None}
    if result["type"] == "ACCEPTANCE":
        action = Action(case_id=case.id, type="VERIFY_EXECUTION", status="OPEN", payload_json={})
        db.add(action)
        db.flush()
        case.current_action_id = action.id
        case.status = "RESOLVED_PENDING_EXECUTION"
        audit(db, case.id, "CLAIM_ACCEPTED_PENDING_EXECUTION", {"action_id": action.id})
        db.commit()
        return {"analysis": result, "case_status": case.status, "updated_diagnosis": None}
    try:
        updated, _, _ = diagnose(db, case)
        body = updated.to_dict()
    except ValueError:
        body = None
    return {"analysis": result, "case_status": case.status, "updated_diagnosis": body}


@router.post("/{case_id}/outcome")
def outcome(case_id: str, payload: OutcomeInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    existing = db.scalars(select(Outcome).where(Outcome.case_id == case.id)).first()
    outcome_row = existing or Outcome(case_id=case.id, result_type=payload.result_type)
    if not existing:
        db.add(outcome_row)
    outcome_row.result_type = payload.result_type
    outcome_row.amount_recovered = payload.amount_recovered
    outcome_row.verified_by_user = payload.verified_by_user
    if payload.verified_by_user:
        case.status = "RESOLVED"
        outcome_row.resolved_at = datetime.now(timezone.utc)
    else:
        case.status = "RESOLVED_PENDING_EXECUTION"
    audit(db, case.id, "OUTCOME_RECORDED", {
        "result": payload.result_type, "verified": payload.verified_by_user,
    })
    db.commit()
    return {"case_status": case.status, "verified": outcome_row.verified_by_user}
