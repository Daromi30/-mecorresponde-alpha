from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..documents import save_upload
from ..engine.deadlines import add_business_days
from ..models import Action, Case, Deadline, Decision, Document, Evidence, Fact, Outcome
from ..reviews import HumanReview
from ..schemas_v2 import (
    CaseCreate, ChargesInput, DocumentFactConfirm, FactUpsert, HumanReviewComplete,
    OutcomeInput, ResponseInput, SubmissionInput,
)
from ..security import (
    CaseAccess, generate_case_token, hash_case_token, require_case_access,
    set_case_access_cookie,
)
from ..services_v2 import (
    analyze_company_response, audit, confirm_document_fact, create_case, create_human_review,
    diagnose, get_next_question, prepare_claim_package, upsert_fact,
)
from ..storage import UnsafeDocumentUpload

router = APIRouter(
    prefix="/api/cases",
    tags=["cases"],
    dependencies=[Depends(require_case_access)],
)


def case_or_404(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def serialize_case(db: Session, case: Case):
    facts = db.scalars(select(Fact).where(Fact.case_id == case.id).order_by(Fact.created_at.asc())).all()
    decisions = db.scalars(select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())).all()
    actions = db.scalars(select(Action).where(Action.case_id == case.id).order_by(Action.id.desc())).all()
    deadlines = db.scalars(select(Deadline).where(Deadline.case_id == case.id)).all()
    evidence = db.scalars(select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.created_at.asc())).all()
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
                "id": fact.id,
                "key": fact.key,
                "value": fact.value_json.get("value"),
                "state": fact.state,
                "user_confirmed": fact.user_confirmed,
                "created_by": fact.created_by,
                "supersedes_fact_id": fact.supersedes_fact_id,
            }
            for fact in facts
        ],
        "evidence": [
            {
                "id": item.id,
                "fact_id": item.fact_id,
                "document_id": item.document_id,
                "source_type": item.source_type,
                "locator": item.locator,
                "excerpt": item.excerpt,
                "strength": item.strength,
            }
            for item in evidence
        ],
        "decisions": [
            {
                "id": decision.id,
                "viability": decision.viability,
                "scope_status": decision.scope_status,
                "economic_value": decision.economic_value,
                "claimable_amount": decision.claimable_amount,
                "worth_pursuing": decision.worth_pursuing,
                "reasoning_summary": decision.reasoning_summary,
                "counterarguments": decision.counterarguments_snapshot,
                "rule_evaluations": decision.rule_evaluations_json,
                "created_at": decision.created_at,
            }
            for decision in decisions
        ],
        "actions": [
            {"id": action.id, "type": action.type, "status": action.status, "payload": action.payload_json}
            for action in actions
        ],
        "deadlines": [
            {"id": deadline.id, "type": deadline.deadline_type, "computed_date": deadline.computed_date, "status": deadline.status}
            for deadline in deadlines
        ],
        "human_reviews": [
            {
                "id": review.id,
                "reason": review.reason,
                "priority": review.priority,
                "status": review.status,
                "reviewer_decision": review.reviewer_decision,
            }
            for review in reviews
        ],
    }


@router.post("")
def create(payload: CaseCreate, response: Response, db: Session = Depends(get_db)):
    token = generate_case_token()
    case = create_case(db, payload.message)
    db.add(CaseAccess(case_id=case.id, token_hash=hash_case_token(token)))
    audit(db, case.id, "CASE_ACCESS_ISSUED", {"method": "anonymous_case_token"})
    db.commit()
    set_case_access_cookie(response, case.id, token)
    return {
        **serialize_case(db, case),
        "next_question": get_next_question(db, case),
        "access_token": token,
    }


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    return serialize_case(db, case_or_404(db, case_id))


@router.get("/{case_id}/next-question")
def question(case_id: str, db: Session = Depends(get_db)):
    return get_next_question(db, case_or_404(db, case_id))


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
        db,
        case,
        payload.key,
        value,
        payload.state,
        payload.materiality,
        payload.confidence,
        payload.user_confirmed,
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
    key = key_by_family.get(case.family or "")
    if not key:
        raise HTTPException(422, "This case family does not use the charges endpoint")
    values = [item.model_dump(mode="json") for item in payload.charges]
    created = upsert_fact(db, case, key, values, state="confirmed", user_confirmed=True)
    return {"fact_id": created.id, "fact_key": key, "next_question": get_next_question(db, case)}


@router.post("/{case_id}/documents")
async def documents(case_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"Max {settings.max_upload_bytes // (1024 * 1024)} MB in internal alpha")
    try:
        document, extraction = save_upload(
            db,
            case,
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            data,
        )
    except UnsafeDocumentUpload as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "document_id": document.id,
        "status": document.processing_status,
        "extracted": extraction.structured_json,
        "quality_flags": extraction.quality_flags,
    }


@router.post("/{case_id}/documents/{document_id}/confirm-fact")
def document_fact(
    case_id: str,
    document_id: str,
    payload: DocumentFactConfirm,
    db: Session = Depends(get_db),
):
    case = case_or_404(db, case_id)
    document = db.get(Document, document_id)
    if not document or document.case_id != case.id:
        raise HTTPException(404, "Document not found in case")
    created = confirm_document_fact(
        db,
        case,
        document,
        key=payload.key,
        value=payload.value,
        locator=payload.locator,
        excerpt=payload.excerpt,
        materiality=payload.materiality,
    )
    return {
        "fact_id": created.id,
        "evidence_linked": True,
        "next_question": get_next_question(db, case),
    }


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
        "submitted_on": str(payload.submitted_on),
        "reference": payload.reference_number,
        "channel": payload.channel,
    })

    if case.vertical != "electricity":
        db.commit()
        return {
            "status": case.status,
            "deadline": None,
            "deadline_status": "NOT_CONFIGURED",
            "warning": "No se aplica un plazo sectorial no verificado a esta familia.",
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
        "status": case.status,
        "deadline": target,
        "deadline_status": status,
        "warning": None if status == "ACTIVE" else "Calendar is provisional until official applicable holidays are configured.",
    }


@router.post("/{case_id}/responses")
def response(case_id: str, payload: ResponseInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    result = analyze_company_response(db, case, payload.text)

    if result["type"] == "UNKNOWN":
        review = create_human_review(
            db,
            case,
            reason="UNRECOGNIZED_COMPANY_RESPONSE",
            priority="HIGH",
            context={"text": payload.text[:2000]},
        )
        action = Action(
            case_id=case.id,
            type="HUMAN_REVIEW",
            status="OPEN",
            payload_json={"reason": review.reason},
        )
        db.add(action)
        db.flush()
        case.current_action_id = action.id
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

    updated = None
    if case.family in {"E02-A", "E02-B", "E03", "E04-A", "E04-B", "E05", "C01", "C02", "C03", "C04", "C05"}:
        try:
            diagnosis, _, _ = diagnose(db, case)
            updated = diagnosis.to_dict()
        except ValueError:
            updated = None
    return {"analysis": result, "case_status": case.status, "updated_diagnosis": updated}


@router.get("/{case_id}/reviews")
def reviews(case_id: str, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    rows = db.scalars(
        select(HumanReview)
        .where(HumanReview.case_id == case.id)
        .order_by(HumanReview.created_at.desc())
    ).all()
    return [
        {
            "id": review.id,
            "reason": review.reason,
            "priority": review.priority,
            "status": review.status,
            "context": review.context_json,
            "reviewer_decision": review.reviewer_decision,
        }
        for review in rows
    ]


@router.post("/{case_id}/reviews/{review_id}/complete")
def complete_review(
    case_id: str,
    review_id: str,
    payload: HumanReviewComplete,
    db: Session = Depends(get_db),
):
    case = case_or_404(db, case_id)
    review = db.get(HumanReview, review_id)
    if not review or review.case_id != case.id:
        raise HTTPException(404, "Review not found")
    review.status = "COMPLETED"
    review.reviewer_decision = payload.reviewer_decision
    review.completed_at = datetime.now(timezone.utc)
    if case.status == "HUMAN_REVIEW":
        case.status = "REANALYZING"
    audit(db, case.id, "HUMAN_REVIEW_COMPLETED", {"review_id": review.id})
    db.commit()
    return {"review_id": review.id, "status": review.status, "case_status": case.status}


@router.post("/{case_id}/outcome")
def outcome(case_id: str, payload: OutcomeInput, db: Session = Depends(get_db)):
    case = case_or_404(db, case_id)
    existing = db.scalars(select(Outcome).where(Outcome.case_id == case.id)).first()
    if existing:
        outcome_row = existing
    else:
        outcome_row = Outcome(case_id=case.id, result_type=payload.result_type)
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
        "result": payload.result_type,
        "verified": payload.verified_by_user,
    })
    db.commit()
    return {"case_status": case.status, "verified": outcome_row.verified_by_user}
