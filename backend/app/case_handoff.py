from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Action,
    Case,
    Communication,
    Counterargument,
    Decision,
    Document,
    Evidence,
    Fact,
    LegalRuleVersion,
    LegalSource,
    Outcome,
    RuleEvaluation,
)
from .reviews import HumanReview


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_case_handoff(db: Session, case: Case) -> dict[str, Any]:
    """Build a claimant-facing case package suitable for assisted/professional handoff.

    The package contains the facts, evidence, decisions, communications and exact
    legal provenance already stored in the resolution engine. It deliberately
    excludes authentication material, internal audit payloads, AI-run telemetry
    and document object-storage keys.
    """

    fact_rows = list(
        db.scalars(
            select(Fact)
            .where(Fact.case_id == case.id)
            .order_by(Fact.created_at.asc())
        ).all()
    )
    latest_by_key: dict[str, Fact] = {}
    for row in fact_rows:
        latest_by_key[row.key] = row

    evidence_rows = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.case_id == case.id)
            .order_by(Evidence.created_at.asc())
        ).all()
    )
    document_rows = list(
        db.scalars(select(Document).where(Document.case_id == case.id)).all()
    )
    decision_rows = list(
        db.scalars(
            select(Decision)
            .where(Decision.case_id == case.id)
            .order_by(Decision.created_at.asc())
        ).all()
    )
    action_rows = list(db.scalars(select(Action).where(Action.case_id == case.id)).all())
    communication_rows = list(
        db.scalars(select(Communication).where(Communication.case_id == case.id)).all()
    )
    counterargument_rows = list(
        db.scalars(select(Counterargument).where(Counterargument.case_id == case.id)).all()
    )
    outcome_rows = list(db.scalars(select(Outcome).where(Outcome.case_id == case.id)).all())
    review_rows = list(
        db.scalars(
            select(HumanReview)
            .where(HumanReview.case_id == case.id)
            .order_by(HumanReview.created_at.asc())
        ).all()
    )
    evaluation_rows = list(
        db.scalars(
            select(RuleEvaluation)
            .where(RuleEvaluation.case_id == case.id)
            .order_by(RuleEvaluation.evaluated_at.asc())
        ).all()
    )

    rule_version_ids = {row.rule_version_id for row in evaluation_rows}
    rule_versions: dict[str, LegalRuleVersion] = {}
    sources: dict[str, LegalSource] = {}
    if rule_version_ids:
        for rule in db.scalars(
            select(LegalRuleVersion).where(LegalRuleVersion.id.in_(rule_version_ids))
        ).all():
            rule_versions[rule.id] = rule
        source_ids = {rule.source_id for rule in rule_versions.values()}
        if source_ids:
            for source in db.scalars(
                select(LegalSource).where(LegalSource.id.in_(source_ids))
            ).all():
                sources[source.id] = source

    provenance: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    for evaluation in evaluation_rows:
        rule = rule_versions.get(evaluation.rule_version_id)
        if not rule or rule.id in seen_versions:
            continue
        source = sources.get(rule.source_id)
        provenance.append(
            {
                "rule_version_id": rule.id,
                "rule_id": rule.rule_id,
                "version": rule.version,
                "valid_from": _json_value(rule.valid_from),
                "valid_to": _json_value(rule.valid_to),
                "article": rule.article,
                "review_status": rule.review_status,
                "source": (
                    {
                        "id": source.id,
                        "authority": source.authority,
                        "title": source.title,
                        "official_url": source.official_url,
                        "publication_date": _json_value(source.publication_date),
                        "jurisdiction": source.jurisdiction,
                        "status": source.status,
                    }
                    if source
                    else None
                ),
            }
        )
        seen_versions.add(rule.id)

    latest_decision = decision_rows[-1] if decision_rows else None
    open_reviews = [row for row in review_rows if row.status == "OPEN"]

    def serialize_fact(row: Fact) -> dict[str, Any]:
        return {
            "id": row.id,
            "key": row.key,
            "value": row.value_json.get("value"),
            "state": row.state,
            "materiality": row.materiality,
            "confidence": row.confidence,
            "user_confirmed": row.user_confirmed,
            "created_by": row.created_by,
            "supersedes_fact_id": row.supersedes_fact_id,
            "created_at": _json_value(row.created_at),
        }

    return {
        "package_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "single_case_resolution_handoff",
        "notice": (
            "Este paquete resume el expediente y su trazabilidad. No sustituye una revisión profesional "
            "cuando el propio expediente la requiera."
        ),
        "case": {
            "id": case.id,
            "status": case.status,
            "service_level": case.service_level,
            "vertical": case.vertical,
            "family": case.family,
            "jurisdiction": case.jurisdiction,
            "title": case.title,
            "raw_intake": case.raw_intake,
            "opened_at": _json_value(case.opened_at),
            "closed_at": _json_value(case.closed_at),
            "current_decision_id": case.current_decision_id,
            "current_action_id": case.current_action_id,
        },
        "current_facts": [
            serialize_fact(latest_by_key[key]) for key in sorted(latest_by_key)
        ],
        "fact_history": [serialize_fact(row) for row in fact_rows],
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
            for row in evidence_rows
        ],
        "documents": [
            {
                "id": row.id,
                "original_filename": row.original_filename,
                "mime_type": row.mime_type,
                "sha256": row.sha256,
                "document_type": row.document_type,
                "processing_status": row.processing_status,
                "page_count": row.page_count,
                "contains_sensitive_data": row.contains_sensitive_data,
                "uploaded_at": _json_value(row.uploaded_at),
                "binary_included": False,
            }
            for row in document_rows
        ],
        "latest_decision": (
            {
                "id": latest_decision.id,
                "viability": latest_decision.viability,
                "scope_status": latest_decision.scope_status,
                "economic_value": latest_decision.economic_value,
                "claimable_amount": latest_decision.claimable_amount,
                "worth_pursuing": latest_decision.worth_pursuing,
                "professional_review_required": latest_decision.professional_review_required,
                "reasoning_summary": latest_decision.reasoning_summary,
                "created_at": _json_value(latest_decision.created_at),
            }
            if latest_decision
            else None
        ),
        "decision_history": [
            {
                "id": row.id,
                "viability": row.viability,
                "scope_status": row.scope_status,
                "economic_value": row.economic_value,
                "claimable_amount": row.claimable_amount,
                "worth_pursuing": row.worth_pursuing,
                "professional_review_required": row.professional_review_required,
                "reasoning_summary": row.reasoning_summary,
                "created_at": _json_value(row.created_at),
            }
            for row in decision_rows
        ],
        "legal_provenance": provenance,
        "rule_evaluations": [
            {
                "id": row.id,
                "rule_version_id": row.rule_version_id,
                "result": row.result,
                "missing_conditions": row.missing_conditions,
                "failed_conditions": row.failed_conditions,
                "engine_version": row.engine_version,
                "evaluated_at": _json_value(row.evaluated_at),
            }
            for row in evaluation_rows
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
            for row in counterargument_rows
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
            for row in action_rows
        ],
        "communications": [
            {
                "id": row.id,
                "direction": row.direction,
                "channel": row.channel,
                "body": row.body,
                "occurred_on": _json_value(row.occurred_on),
                "sent_at": _json_value(row.sent_at),
                "received_at": _json_value(row.received_at),
                "reference_number": row.reference_number,
                "document_id": row.document_id,
            }
            for row in communication_rows
        ],
        "human_reviews": [
            {
                "id": row.id,
                "reason": row.reason,
                "priority": row.priority,
                "status": row.status,
                "reviewer_decision": row.reviewer_decision,
                "created_at": _json_value(row.created_at),
                "completed_at": _json_value(row.completed_at),
            }
            for row in review_rows
        ],
        "open_human_review_count": len(open_reviews),
        "outcomes": [
            {
                "id": row.id,
                "result_type": row.result_type,
                "amount_requested": row.amount_requested,
                "amount_recovered": row.amount_recovered,
                "non_monetary_result": row.non_monetary_result,
                "resolution_channel": row.resolution_channel,
                "resolved_on": _json_value(row.resolved_on),
                "resolved_at": _json_value(row.resolved_at),
                "verified_by_user": row.verified_by_user,
                "failure_reason": row.failure_reason,
            }
            for row in outcome_rows
        ],
        "excluded_internal_data": [
            "authentication_secrets",
            "anonymous_access_token_hashes",
            "internal_audit_payloads",
            "ai_run_telemetry",
            "document_storage_keys",
        ],
    }
