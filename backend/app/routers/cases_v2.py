from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..engine.deadlines import add_business_days
from ..models import Action, Case, Deadline, Decision, Document, Evidence, Fact, Outcome
from ..reviews import HumanReview
from ..schemas_v2 import (
    CaseCreate, ChargesInput, DocumentFactConfirm, FactUpsert, HumanReviewComplete,
    OutcomeInput, ResponseInput, SubmissionInput,
)
from ..services_v2 import (
    analyze_company_response, audit, confirm_document_fact, create_case, create_human_review,
    diagnose, get_next_question, prepare_claim_package, save_upload, upsert_fact,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])


def case_or_404(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    return c


def serialize_case(db: Session, c: Case):
    facts = db.scalars(select(Fact).where(Fact.case_id == c.id).order_by(Fact.created_at.asc())).all()
    decisions = db.scalars(select(Decision).where(Decision.case_id == c.id).order_by(Decision.created_at.desc())).all()
    actions = db.scalars(select(Action).where(Action.case_id == c.id).order_by(Action.id.desc())).all()
    deadlines = db.scalars(select(Deadline).where(Deadline.case_id == c.id)).all()
    evidence = db.scalars(select(Evidence).where(Evidence.case_id == c.id).order_by(Evidence.created_at.asc())).all()
    reviews = db.scalars(select(HumanReview).where(HumanReview.case_id == c.id).order_by(HumanReview.created_at.desc())).all()
    return {
        "id": c.id,
        "status": c.status,
        "vertical": c.vertical,
        "family": c.family,
        "title": c.title,
        "raw_intake": c.raw_intake,
        "current_decision_id": c.current_decision_id,
        "current_action_id": c.current_action_id,
        "opened_at": c.opened_at,
        "facts": [{"id": f.id, "key": f.key, "value": f.value_json.get("value"), "state": f.state, "user_confirmed": f.user_confirmed, "created_by": f.created_by} for f in facts],
        "evidence": [{"id": e.id, "fact_id": e.fact_id, "document_id": e.document_id, "source_type": e.source_type, "locator": e.locator, "strength": e.strength} for e in evidence],
        "decisions": [{"id": d.id, "viability": d.viability, "claimable_amount": d.claimable_amount, "worth_pursuing": d.worth_pursuing, "reasoning_summary": d.reasoning_summary, "created_at": d.created_at} for d in decisions],
        "actions": [{"id": a.id, "type": a.type, "status": a.status, "payload": a.payload_json} for a in actions],
        "deadlines": [{"id": x.id, "type": x.deadline_type, "computed_date": x.computed_date, "status": x.status} for x in deadlines],
        "human_reviews": [{"id": r.id, "reason": r.reason, "priority": r.priority, "status": r.status, "reviewer_decision": r.reviewer_decision} for r in reviews],
    }


@router.post("")
def create(payload: CaseCreate, db: Session = Depends(get_db)):
    c = create_case(db, payload.message)
    return {**serialize_case(db, c), "next_question": get_next_question(db, c)}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    return serialize_case(db, case_or_404(db, case_id))


@router.get("/{case_id}/next-question")
def question(case_id: str, db: Session = Depends(get_db)):
    return get_next_question(db, case_or_404(db, case_id))


@router.post("/{case_id}/facts")
def fact(case_id: str, payload: FactUpsert, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    value = payload.value
    if payload.key in {"electricity.supply_end_date", "electricity.billing.invoice_date", "electricity.addon.first_charge_date"} and isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            raise HTTPException(422, "Use YYYY-MM-DD")
    f = upsert_fact(db, c, payload.key, value, payload.state, payload.materiality, payload.confidence, payload.user_confirmed)
    return {"fact_id": f.id, "next_question": get_next_question(db, c)}


@router.post("/{case_id}/charges")
def charges(case_id: str, payload: ChargesInput, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    values = [x.model_dump(mode="json") for x in payload.charges]
    key = "electricity.billing.duplicate_charges" if c.family == "E02-B" else "electricity.addon.charges"
    f = upsert_fact(db, c, key, values, state="confirmed", user_confirmed=True)
    return {"fact_id": f.id, "fact_key": key, "next_question": get_next_question(db, c)}


@router.post("/{case_id}/documents")
async def documents(case_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Max 15 MB in internal alpha")
    doc, ext = save_upload(db, c, file.filename or "upload", file.content_type or "application/octet-stream", data)
    return {"document_id": doc.id, "status": doc.processing_status, "extracted": ext.structured_json, "quality_flags": ext.quality_flags}


@router.post("/{case_id}/documents/{document_id}/confirm-fact")
def document_fact(case_id: str, document_id: str, payload: DocumentFactConfirm, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    doc = db.get(Document, document_id)
    if not doc or doc.case_id != c.id:
        raise HTTPException(404, "Document not found in case")
    f = confirm_document_fact(db, c, doc, key=payload.key, value=payload.value, locator=payload.locator, excerpt=payload.excerpt, materiality=payload.materiality)
    return {"fact_id": f.id, "evidence_linked": True, "next_question": get_next_question(db, c)}


@router.post("/{case_id}/diagnose")
def run_diagnosis(case_id: str, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    try:
        result, dec, action = diagnose(db, c)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**result.to_dict(), "decision_id": dec.id, "action_id": action.id}


@router.post("/{case_id}/prepare-claim")
def prepare_claim(case_id: str, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    try:
        return prepare_claim_package(db, c)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/{case_id}/submission")
def submission(case_id: str, payload: SubmissionInput, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    holiday_set = set()
    if settings.legal_holidays_csv:
        for raw in settings.legal_holidays_csv.split(","):
            if raw.strip():
                holiday_set.add(date.fromisoformat(raw.strip()))
    target = add_business_days(payload.submitted_on, 15, holiday_set)
    status = "ACTIVE" if settings.legal_holidays_csv else "PROVISIONAL_CALENDAR"
    d = Deadline(case_id=c.id, deadline_type="ELECTRICITY_COMPLAINT_RESPONSE", trigger_event="VERIFIED_INITIAL_CLAIM_SUBMISSION", trigger_date=payload.submitted_on, computed_date=target, status=status)
    db.add(d)
    c.status = "WAITING_RESPONSE"
    audit(db, c.id, "CLAIM_SUBMITTED", {"submitted_on": str(payload.submitted_on), "reference": payload.reference_number, "deadline_status": status})
    db.commit()
    return {"status": c.status, "deadline": target, "deadline_status": status, "warning": None if status == "ACTIVE" else "Calendar is provisional until official applicable holidays are configured."}


@router.post("/{case_id}/responses")
def response(case_id: str, payload: ResponseInput, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    result = analyze_company_response(db, c, payload.text)
    updated = None
    if result["type"] != "UNKNOWN" and c.family in {"E04-A", "E04-B", "E02-A", "E02-B"}:
        try:
            d, _, _ = diagnose(db, c)
            updated = d.to_dict()
        except ValueError:
            updated = None
    elif result["type"] == "UNKNOWN":
        review = create_human_review(db, c, reason="UNRECOGNIZED_COMPANY_RESPONSE", priority="HIGH", context={"text": payload.text[:2000]})
        a = Action(case_id=c.id, type="HUMAN_REVIEW", status="OPEN", payload_json={"reason": review.reason})
        db.add(a)
        db.flush()
        c.current_action_id = a.id
        db.commit()
    return {"analysis": result, "case_status": c.status, "updated_diagnosis": updated}


@router.get("/{case_id}/reviews")
def reviews(case_id: str, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    rows = db.scalars(select(HumanReview).where(HumanReview.case_id == c.id).order_by(HumanReview.created_at.desc())).all()
    return [{"id": r.id, "reason": r.reason, "priority": r.priority, "status": r.status, "context": r.context_json, "reviewer_decision": r.reviewer_decision} for r in rows]


@router.post("/{case_id}/reviews/{review_id}/complete")
def complete_review(case_id: str, review_id: str, payload: HumanReviewComplete, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    review = db.get(HumanReview, review_id)
    if not review or review.case_id != c.id:
        raise HTTPException(404, "Review not found")
    review.status = "COMPLETED"
    review.reviewer_decision = payload.reviewer_decision
    review.completed_at = datetime.now(timezone.utc)
    if c.status == "HUMAN_REVIEW":
        c.status = "REANALYZING"
    audit(db, c.id, "HUMAN_REVIEW_COMPLETED", {"review_id": review.id})
    db.commit()
    return {"review_id": review.id, "status": review.status, "case_status": c.status}


@router.post("/{case_id}/outcome")
def outcome(case_id: str, payload: OutcomeInput, db: Session = Depends(get_db)):
    c = case_or_404(db, case_id)
    existing = db.scalars(select(Outcome).where(Outcome.case_id == c.id)).first()
    if existing:
        o = existing
    else:
        o = Outcome(case_id=c.id, result_type=payload.result_type)
        db.add(o)
    o.result_type = payload.result_type
    o.amount_recovered = payload.amount_recovered
    o.verified_by_user = payload.verified_by_user
    if payload.verified_by_user:
        c.status = "RESOLVED"
        o.resolved_at = datetime.now(timezone.utc)
    else:
        c.status = "RESOLVED_PENDING_EXECUTION"
    audit(db, c.id, "OUTCOME_RECORDED", {"result": payload.result_type, "verified": payload.verified_by_user})
    db.commit()
    return {"case_status": c.status, "verified": o.verified_by_user}
