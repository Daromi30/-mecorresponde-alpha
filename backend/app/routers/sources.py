from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Case, Decision, LegalRuleVersion, LegalSource
from ..security import require_case_access

router = APIRouter(
    prefix="/api/cases",
    tags=["legal-sources"],
    dependencies=[Depends(require_case_access)],
)


@router.get("/{case_id}/legal-sources")
def current_legal_sources(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if not case.current_decision_id:
        return {"decision_id": None, "sources": []}

    decision = db.get(Decision, case.current_decision_id)
    if not decision or decision.case_id != case.id:
        raise HTTPException(409, "Current decision is inconsistent")

    sources: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for evaluation in decision.rule_evaluations_json or []:
        rule_id = evaluation.get("rule_id")
        version = evaluation.get("version")
        if not rule_id or version is None or (rule_id, int(version)) in seen:
            continue
        seen.add((rule_id, int(version)))
        rule = db.scalars(
            select(LegalRuleVersion).where(
                LegalRuleVersion.rule_id == rule_id,
                LegalRuleVersion.version == int(version),
            )
        ).first()
        if not rule:
            continue
        source = db.get(LegalSource, rule.source_id)
        if not source:
            continue
        sources.append(
            {
                "rule_id": rule.rule_id,
                "rule_version_id": rule.id,
                "version": rule.version,
                "valid_from": rule.valid_from,
                "valid_to": rule.valid_to,
                "article": rule.article,
                "review_status": rule.review_status,
                "source_id": source.id,
                "authority": source.authority,
                "title": source.title,
                "official_url": source.official_url,
                "jurisdiction": source.jurisdiction,
                "rule_result": evaluation.get("result"),
            }
        )

    return {"decision_id": decision.id, "sources": sources}
