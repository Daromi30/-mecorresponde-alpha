from __future__ import annotations

from typing import Any, Iterable

from .models import Case, Decision, Evidence, Fact
from .reviews import HumanReview


def build_dossier_quality(
    case: Case,
    facts: Iterable[Fact],
    evidence: Iterable[Evidence],
    decisions: Iterable[Decision],
    reviews: Iterable[HumanReview],
) -> dict[str, Any]:
    """Describe dossier readiness without inventing a legal confidence score.

    This profile is intentionally factual. It reports confirmation/evidence coverage and
    workflow gates, but never converts them into a probability of legal success.
    """
    fact_rows = list(facts)
    evidence_rows = list(evidence)
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
    current_decision = next(
        (d for d in decision_rows if d.id == case.current_decision_id),
        decision_rows[0] if decision_rows else None,
    )

    if case.status == "CLOSED_UNSUPPORTED":
        readiness = "OUT_OF_AUTOMATED_SCOPE"
    elif open_reviews or case.status == "HUMAN_REVIEW":
        readiness = "HUMAN_REVIEW_REQUIRED"
    elif case.status == "NEEDS_INFORMATION" or unknown:
        readiness = "NEEDS_INFORMATION"
    elif case.status == "READY_TO_SUBMIT":
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
            "Este perfil describe la calidad factual y documental del expediente. "
            "No es una probabilidad de éxito jurídico."
        ),
    }
