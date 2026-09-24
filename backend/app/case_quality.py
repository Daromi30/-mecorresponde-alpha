from __future__ import annotations

from typing import Any, Iterable

from .models import Case, Decision, Evidence, Fact
from .reviews import HumanReview


def _active_fact_rows(facts: list[Fact]) -> list[Fact]:
    """Return only facts that have not been superseded by a later fact.

    Facts are immutable history rows. Quality/readiness must describe the current
    dossier, not count stale values that were explicitly replaced. The supersedes
    chain is authoritative; as a defensive fallback, if multiple unsuperseded rows
    share a key, keep the last row supplied by the caller (the API queries facts in
    ascending creation order).
    """
    superseded_ids = {
        fact.supersedes_fact_id
        for fact in facts
        if fact.supersedes_fact_id
    }
    candidates = [fact for fact in facts if fact.id not in superseded_ids]
    latest_by_key: dict[str, Fact] = {}
    for fact in candidates:
        latest_by_key[fact.key] = fact
    return list(latest_by_key.values())


def build_dossier_quality(
    case: Case,
    facts: Iterable[Fact],
    evidence: Iterable[Evidence],
    decisions: Iterable[Decision],
    reviews: Iterable[HumanReview],
) -> dict[str, Any]:
    """Describe current dossier readiness without inventing a legal confidence score.

    Historical facts remain available elsewhere for auditability, but this profile
    reports the active factual state only. Evidence attached solely to a superseded
    fact does not inflate current documentary coverage.
    """
    fact_history = list(facts)
    fact_rows = _active_fact_rows(fact_history)
    active_fact_ids = {fact.id for fact in fact_rows}
    evidence_history = list(evidence)
    evidence_rows = [
        item
        for item in evidence_history
        if item.fact_id is None or item.fact_id in active_fact_ids
    ]
    decision_rows = list(decisions)
    review_rows = list(reviews)

    confirmed = [f for f in fact_rows if f.state == "confirmed" or f.user_confirmed]
    unknown = [f for f in fact_rows if f.state == "unknown"]
    asserted = [f for f in fact_rows if f not in confirmed and f not in unknown]
    critical = [f for f in fact_rows if f.materiality == "critical"]
    critical_confirmed = [f for f in critical if f.state == "confirmed" or f.user_confirmed]

    documentary_fact_ids = {
        item.fact_id
        for item in evidence_rows
        if item.fact_id and item.source_type == "document"
    }
    strong_fact_ids = {
        item.fact_id
        for item in evidence_rows
        if item.fact_id and item.strength == "strong"
    }
    company_fact_ids = {
        item.fact_id
        for item in evidence_rows
        if item.fact_id and item.source_type == "company"
    }
    human_fact_ids = {
        item.fact_id
        for item in evidence_rows
        if item.fact_id and item.source_type == "human"
    }

    open_reviews = [r for r in review_rows if r.status == "OPEN"]
    # An invalidated decision remains in the audit history, but it is not the
    # current diagnosis. Never revive it merely because it is the newest row.
    current_decision = next(
        (
            d for d in decision_rows
            if case.current_decision_id is not None
            and d.id == case.current_decision_id
            and d.case_id == case.id
        ),
        None,
    )

    if case.status == "CLOSED_UNSUPPORTED":
        readiness = "OUT_OF_AUTOMATED_SCOPE"
    elif open_reviews or case.status == "HUMAN_REVIEW":
        readiness = "HUMAN_REVIEW_REQUIRED"
    elif case.status == "NEEDS_INFORMATION" or unknown:
        readiness = "NEEDS_INFORMATION"
    elif case.status == "READY_TO_SUBMIT" and current_decision is not None:
        readiness = "ACTION_READY"
    elif current_decision is not None:
        readiness = "DIAGNOSIS_AVAILABLE"
    else:
        readiness = "INTAKE"

    return {
        "readiness": readiness,
        "facts": {
            "total": len(fact_rows),
            "confirmed": len(confirmed),
            "asserted": len(asserted),
            "unknown": len(unknown),
            "critical_total": len(critical),
            "critical_confirmed": len(critical_confirmed),
        },
        "evidence": {
            "links_total": len(evidence_rows),
            "document_supported_facts": len(documentary_fact_ids),
            "strong_supported_facts": len(strong_fact_ids),
            "company_asserted_facts": len(company_fact_ids),
            "human_supported_facts": len(human_fact_ids),
        },
        "gates": {
            "open_human_reviews": len(open_reviews),
            "professional_review_required": bool(
                current_decision and current_decision.professional_review_required
            ),
            "current_decision_id": current_decision.id if current_decision else None,
            "rules_evaluated": len(current_decision.rule_evaluations_json or [])
            if current_decision
            else 0,
        },
        "note": (
            "Este perfil describe la calidad factual y documental actual del expediente. "
            "El historial sustituido se conserva para trazabilidad, pero no infla estas métricas. "
            "No es una probabilidad de éxito jurídico."
        ),
    }
