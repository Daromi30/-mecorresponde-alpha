from __future__ import annotations

from math import isclose

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AIRun, AuditEvent, Case, Communication, Outcome
from .routers import quality as quality_router


_INSTALLED = False


def _audit_exists(db: Session, case_id: str, event_type: str) -> bool:
    return bool(
        db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.case_id == case_id,
                AuditEvent.event_type == event_type,
            )
        )
    )


def _recoverable_outcome(db: Session, case: Case) -> Outcome | None:
    if case.status != "RESOLVED" or _audit_exists(db, case.id, "OUTCOME_EVIDENCE_RECORDED"):
        return None
    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case.id))
    if outcome is None or not outcome.verified_by_user or outcome.resolved_at is None:
        return None
    return outcome


def _response_metadata_ids(db: Session, case_id: str) -> set[str]:
    rows = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "COMPANY_RESPONSE_RECORDED",
        )
    ).all()
    return {
        str((row.payload_json or {}).get("communication_id"))
        for row in rows
        if (row.payload_json or {}).get("communication_id")
    }


def _recoverable_response(db: Session, case: Case) -> tuple[Communication, AIRun] | None:
    # A successful base response transition no longer remains in WAITING_RESPONSE. Recovery
    # here is deliberately narrower than ordinary response processing: it is only for the
    # window where analysis/state were committed but the evidence metadata was not.
    if case.status == "WAITING_RESPONSE":
        return None
    submitted = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    )
    if not submitted:
        return None

    linked = _response_metadata_ids(db, case.id)
    orphan_rows = db.scalars(
        select(Communication)
        .where(
            Communication.case_id == case.id,
            Communication.direction == "INBOUND",
        )
        .order_by(Communication.received_at.desc())
    ).all()
    orphans = [row for row in orphan_rows if row.id not in linked]
    if len(orphans) != 1:
        return None

    analysis_run = db.scalars(
        select(AIRun)
        .where(AIRun.case_id == case.id, AIRun.task == "analyze_response")
        .order_by(AIRun.created_at.desc())
    ).first()
    if analysis_run is None:
        return None
    return orphans[0], analysis_run


def install_evidenced_recovery_policy() -> None:
    """Make evidenced response/outcome retries recover an already-committed base transition.

    The evidence-aware routes historically called a state-advancing base workflow that commits
    before attaching the user's real-world date/channel/reference/detail. If the final metadata
    commit failed, a retry was rejected because the case had already advanced. These wrappers
    recognize only that exact stranded shape and finish the evidence layer without replaying the
    legal analysis, response facts, workflow actions, or outcome verification timestamp.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_require_response = quality_router._require_waiting_for_company_response
    previous_process_response = quality_router.process_company_response
    previous_require_outcome = quality_router._require_pending_execution_verification
    previous_process_outcome = quality_router.process_outcome

    def require_response_or_recovery(db: Session, case: Case) -> None:
        try:
            previous_require_response(db, case)
            return
        except HTTPException as exc:
            if exc.status_code != 409 or _recoverable_response(db, case) is None:
                raise

    def process_response_or_recover(case_id, payload, db: Session):
        case = db.get(Case, case_id)
        recovery = _recoverable_response(db, case) if case is not None else None
        if recovery is None:
            return previous_process_response(case_id, payload, db)

        orphan, analysis_run = recovery
        if (orphan.body or "") != payload.text:
            raise HTTPException(
                status_code=409,
                detail="The pending response evidence does not match the already analyzed company response",
            )

        # The evidenced route captured the orphan's id before calling this function and links
        # metadata only to a newly observed id. Replace the unlinked row rather than replaying
        # analysis. No evidence audit references the orphan, so the id is not externally bound.
        replacement = Communication(
            case_id=orphan.case_id,
            direction=orphan.direction,
            channel=orphan.channel,
            body=orphan.body,
            occurred_on=orphan.occurred_on,
            sent_at=orphan.sent_at,
            received_at=orphan.received_at,
            reference_number=orphan.reference_number,
            document_id=orphan.document_id,
        )
        db.add(replacement)
        db.delete(orphan)
        db.flush()
        return {
            "analysis": analysis_run.structured_output,
            "case_status": case.status,
            "updated_diagnosis": None,
        }

    def require_outcome_or_recovery(db: Session, case: Case) -> None:
        try:
            previous_require_outcome(db, case)
            return
        except HTTPException as exc:
            if exc.status_code != 409 or _recoverable_outcome(db, case) is None:
                raise

    def process_outcome_or_recover(case_id, payload, db: Session):
        case = db.get(Case, case_id)
        outcome = _recoverable_outcome(db, case) if case is not None else None
        if outcome is None:
            return previous_process_outcome(case_id, payload, db)

        same_amount = (
            outcome.amount_recovered is None and payload.amount_recovered is None
        ) or (
            outcome.amount_recovered is not None
            and payload.amount_recovered is not None
            and isclose(float(outcome.amount_recovered), float(payload.amount_recovered), abs_tol=1e-9)
        )
        if (
            payload.verified_by_user is not True
            or payload.result_type != outcome.result_type
            or not same_amount
        ):
            raise HTTPException(
                status_code=409,
                detail="The pending outcome evidence does not match the already verified outcome",
            )
        return {"case_status": case.status, "verified": True}

    quality_router._require_waiting_for_company_response = require_response_or_recovery
    quality_router.process_company_response = process_response_or_recover
    quality_router._require_pending_execution_verification = require_outcome_or_recovery
    quality_router.process_outcome = process_outcome_or_recover
    _INSTALLED = True
