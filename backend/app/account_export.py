from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import User, UserSession
from .models import (
    AIRun,
    Action,
    AuditEvent,
    Calculation,
    Case,
    Communication,
    Counterargument,
    Deadline,
    Decision,
    Document,
    DocumentExtraction,
    Evidence,
    Fact,
    Outcome,
    RuleEvaluation,
)
from .reviews import HumanReview


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _group_by_case(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.case_id].append(row)
    return grouped


def build_account_export(db: Session, user: User) -> dict[str, Any]:
    """Build a user-facing structured copy without authentication secrets.

    This is deliberately not labelled as a GDPR portability/compliance export.
    It is a practical copy of the account and owned-case data currently stored by
    MECORRESPONDE. Password hashes, session token hashes, anonymous access token
    hashes, admin secrets and document object-storage keys are never exported.
    """

    cases = db.scalars(
        select(Case).where(Case.user_id == user.id).order_by(Case.created_at.asc())
    ).all()
    case_ids = [case.id for case in cases]

    sessions = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id)
        .order_by(UserSession.created_at.asc())
    ).all()

    if not case_ids:
        return {
            "export_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "structured_account_and_owned_case_data",
            "document_files_included": False,
            "document_files_note": (
                "Los archivos binarios originales no se incluyen en esta copia JSON. "
                "Sí se incluye la información y extracción estructurada que MECORRESPONDE guarda sobre ellos."
            ),
            "account": {
                "id": user.id,
                "email": user.email,
                "email_verified_at": _json_value(user.email_verified_at),
                "disabled_at": _json_value(user.disabled_at),
                "created_at": _json_value(user.created_at),
                "updated_at": _json_value(user.updated_at),
            },
            "sessions": [
                {
                    "id": session.id,
                    "created_at": _json_value(session.created_at),
                    "expires_at": _json_value(session.expires_at),
                    "revoked_at": _json_value(session.revoked_at),
                }
                for session in sessions
            ],
            "cases": [],
        }

    def rows_for(model: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.case_id.in_(case_ids))).all())

    facts = _group_by_case(rows_for(Fact))
    evidence = _group_by_case(rows_for(Evidence))
    decisions = _group_by_case(rows_for(Decision))
    actions = _group_by_case(rows_for(Action))
    deadlines = _group_by_case(rows_for(Deadline))
    communications = _group_by_case(rows_for(Communication))
    outcomes = _group_by_case(rows_for(Outcome))
    audits = _group_by_case(rows_for(AuditEvent))
    ai_runs = _group_by_case(rows_for(AIRun))
    counterarguments = _group_by_case(rows_for(Counterargument))
    calculations = _group_by_case(rows_for(Calculation))
    rule_evaluations = _group_by_case(rows_for(RuleEvaluation))
    reviews = _group_by_case(rows_for(HumanReview))
    documents = rows_for(Document)
    documents_by_case = _group_by_case(documents)

    document_ids = [document.id for document in documents]
    extraction_by_document: dict[str, list[DocumentExtraction]] = defaultdict(list)
    if document_ids:
        extraction_rows = db.scalars(
            select(DocumentExtraction).where(DocumentExtraction.document_id.in_(document_ids))
        ).all()
        for extraction in extraction_rows:
            extraction_by_document[extraction.document_id].append(extraction)

    exported_cases: list[dict[str, Any]] = []
    for case in cases:
        exported_cases.append(
            {
                "id": case.id,
                "status": case.status,
                "service_level": case.service_level,
                "vertical": case.vertical,
                "family": case.family,
                "jurisdiction": case.jurisdiction,
                "title": case.title,
                "raw_intake": case.raw_intake,
                "current_decision_id": case.current_decision_id,
                "current_action_id": case.current_action_id,
                "schema_version": case.schema_version,
                "opened_at": _json_value(case.opened_at),
                "closed_at": _json_value(case.closed_at),
                "created_at": _json_value(case.created_at),
                "updated_at": _json_value(case.updated_at),
                "facts": [
                    {
                        "id": row.id,
                        "key": row.key,
                        "value": row.value_json.get("value"),
                        "state": row.state,
                        "materiality": row.materiality,
                        "confidence": row.confidence,
                        "effective_at": _json_value(row.effective_at),
                        "user_confirmed": row.user_confirmed,
                        "created_by": row.created_by,
                        "supersedes_fact_id": row.supersedes_fact_id,
                        "created_at": _json_value(row.created_at),
                    }
                    for row in facts[case.id]
                ],
                "evidence": [
                    {
                        "id": row.id,
                        "fact_id": row.fact_id,
                        "document_id": row.document_id,
                        "source_type": row.source_type,
                        "locator": row.locator,
                        "excerpt": row.excerpt,
                        "strength": row.strength,
                        "created_at": _json_value(row.created_at),
                    }
                    for row in evidence[case.id]
                ],
                "documents": [
                    {
                        "id": document.id,
                        "original_filename": document.original_filename,
                        "mime_type": document.mime_type,
                        "sha256": document.sha256,
                        "document_type": document.document_type,
                        "processing_status": document.processing_status,
                        "page_count": document.page_count,
                        "contains_sensitive_data": document.contains_sensitive_data,
                        "uploaded_at": _json_value(document.uploaded_at),
                        "extractions": [
                            {
                                "id": extraction.id,
                                "extractor_version": extraction.extractor_version,
                                "model_version": extraction.model_version,
                                "raw_text": extraction.raw_text,
                                "structured": extraction.structured_json,
                                "quality_flags": extraction.quality_flags,
                                "started_at": _json_value(extraction.started_at),
                                "completed_at": _json_value(extraction.completed_at),
                            }
                            for extraction in extraction_by_document[document.id]
                        ],
                    }
                    for document in documents_by_case[case.id]
                ],
                "decisions": [
                    {
                        "id": row.id,
                        "viability": row.viability,
                        "scope_status": row.scope_status,
                        "economic_value": row.economic_value,
                        "claimable_amount": row.claimable_amount,
                        "worth_pursuing": row.worth_pursuing,
                        "professional_review_required": row.professional_review_required,
                        "reasoning_summary": row.reasoning_summary,
                        "counterarguments_snapshot": row.counterarguments_snapshot,
                        "rule_evaluations": row.rule_evaluations_json,
                        "created_at": _json_value(row.created_at),
                    }
                    for row in decisions[case.id]
                ],
                "actions": [
                    {
                        "id": row.id,
                        "type": row.type,
                        "status": row.status,
                        "payload": row.payload_json,
                        "due_at": _json_value(row.due_at),
                        "completed_at": _json_value(row.completed_at),
                    }
                    for row in actions[case.id]
                ],
                "deadlines": [
                    {
                        "id": row.id,
                        "type": row.deadline_type,
                        "trigger_event": row.trigger_event,
                        "trigger_date": _json_value(row.trigger_date),
                        "rule_version_id": row.rule_version_id,
                        "calendar_type": row.calendar_type,
                        "computed_date": _json_value(row.computed_date),
                        "status": row.status,
                    }
                    for row in deadlines[case.id]
                ],
                "communications": [
                    {
                        "id": row.id,
                        "direction": row.direction,
                        "channel": row.channel,
                        "body": row.body,
                        "sent_at": _json_value(row.sent_at),
                        "received_at": _json_value(row.received_at),
                        "reference_number": row.reference_number,
                        "document_id": row.document_id,
                    }
                    for row in communications[case.id]
                ],
                "outcomes": [
                    {
                        "id": row.id,
                        "result_type": row.result_type,
                        "amount_requested": row.amount_requested,
                        "amount_recovered": row.amount_recovered,
                        "non_monetary_result": row.non_monetary_result,
                        "resolution_channel": row.resolution_channel,
                        "resolved_at": _json_value(row.resolved_at),
                        "verified_by_user": row.verified_by_user,
                        "failure_reason": row.failure_reason,
                    }
                    for row in outcomes[case.id]
                ],
                "counterarguments": [
                    {
                        "id": row.id,
                        "type": row.type,
                        "origin": row.origin,
                        "description": row.description,
                        "status": row.status,
                        "impact": row.impact,
                    }
                    for row in counterarguments[case.id]
                ],
                "calculations": [
                    {
                        "id": row.id,
                        "type": row.type,
                        "inputs": row.inputs_json,
                        "formula_version": row.formula_version,
                        "result": row.result,
                        "currency": row.currency,
                        "explanation": row.explanation,
                    }
                    for row in calculations[case.id]
                ],
                "rule_evaluations": [
                    {
                        "id": row.id,
                        "rule_version_id": row.rule_version_id,
                        "facts_snapshot": row.facts_snapshot,
                        "result": row.result,
                        "missing_conditions": row.missing_conditions,
                        "failed_conditions": row.failed_conditions,
                        "engine_version": row.engine_version,
                        "evaluated_at": _json_value(row.evaluated_at),
                    }
                    for row in rule_evaluations[case.id]
                ],
                "human_reviews": [
                    {
                        "id": row.id,
                        "reason": row.reason,
                        "priority": row.priority,
                        "status": row.status,
                        "context": row.context_json,
                        "reviewer_decision": row.reviewer_decision,
                        "created_at": _json_value(row.created_at),
                        "completed_at": _json_value(row.completed_at),
                    }
                    for row in reviews[case.id]
                ],
                "audit_events": [
                    {
                        "id": row.id,
                        "event_type": row.event_type,
                        "payload": row.payload_json,
                        "created_at": _json_value(row.created_at),
                    }
                    for row in audits[case.id]
                ],
                "ai_runs": [
                    {
                        "id": row.id,
                        "task": row.task,
                        "provider": row.provider,
                        "model": row.model,
                        "prompt_version": row.prompt_version,
                        "structured_output": row.structured_output,
                        "cost": row.cost,
                        "latency_ms": row.latency_ms,
                        "status": row.status,
                        "created_at": _json_value(row.created_at),
                    }
                    for row in ai_runs[case.id]
                ],
            }
        )

    return {
        "export_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "structured_account_and_owned_case_data",
        "document_files_included": False,
        "document_files_note": (
            "Los archivos binarios originales no se incluyen en esta copia JSON. "
            "Sí se incluye la información y extracción estructurada que MECORRESPONDE guarda sobre ellos."
        ),
        "account": {
            "id": user.id,
            "email": user.email,
            "email_verified_at": _json_value(user.email_verified_at),
            "disabled_at": _json_value(user.disabled_at),
            "created_at": _json_value(user.created_at),
            "updated_at": _json_value(user.updated_at),
        },
        "sessions": [
            {
                "id": session.id,
                "created_at": _json_value(session.created_at),
                "expires_at": _json_value(session.expires_at),
                "revoked_at": _json_value(session.revoked_at),
            }
            for session in sessions
        ],
        "cases": exported_cases,
    }
