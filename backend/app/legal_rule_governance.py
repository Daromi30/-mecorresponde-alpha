"""Separate technical rule execution from professional legal approval."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Case, Decision, LegalRuleVersion, RuleEvaluation


TECHNICAL_DRAFT = "technical_draft"
PROFESSIONALLY_APPROVED = "approved"
TECHNICALLY_EXECUTABLE_STATUSES = frozenset({TECHNICAL_DRAFT, PROFESSIONALLY_APPROVED})


def technically_executable(rule: Any) -> bool:
    """Whether a version may be exercised with synthetic data."""
    return getattr(rule, "review_status", None) in TECHNICALLY_EXECUTABLE_STATUSES


def professionally_approved(rule: Any) -> bool:
    """Return false until exact-version professional evidence is modelled.

    ``reviewed_by`` is legacy free text. It is neither an authenticated legal
    authority nor verifiable evidence and therefore cannot open a real-data
    path. A future professional workflow must bind its evidence to the exact
    rule-version id before this predicate can return true.
    """
    return False


def allowed_for_case(rule: Any, case: Any) -> bool:
    """Only the explicit synthetic mode may execute an unapproved rule."""
    return getattr(case, "mode", None) == "SYNTHETIC" and technically_executable(rule)


def substantive_legal_output_approved(db: Session, case: Case) -> bool:
    """Verify the independent legal gate for one exact current real-case result.

    Operational review is necessary but never sufficient. Professional evidence
    must eventually be authenticated, bound to each exact rule-version id and
    checked for revocation. That evidence model does not exist yet, so
    ``professionally_approved`` keeps this real-data gate closed.
    """
    if case.mode != "PRIVATE_REAL_BETA" or not case.current_decision_id:
        return False
    from .private_beta_release import operational_case_review_approved

    if not operational_case_review_approved(db, case):
        return False
    decision = db.get(Decision, case.current_decision_id)
    if decision is None or decision.case_id != case.id or decision.invalidated_at is not None:
        return False
    latest = db.scalar(
        select(Decision)
        .where(Decision.case_id == case.id, Decision.invalidated_at.is_(None))
        .order_by(Decision.created_at.desc(), Decision.id.desc())
    )
    if latest is None or latest.id != decision.id:
        return False
    evaluations = decision.rule_evaluations_json or []
    if not isinstance(evaluations, list) or not evaluations:
        return False
    seen: set[tuple[str, int]] = set()
    seen_evaluations: set[str] = set()
    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            return False
        rule_id = str(evaluation.get("rule_id") or "")
        try:
            version = int(evaluation.get("version"))
        except (TypeError, ValueError):
            return False
        key = (rule_id, version)
        if not rule_id or version < 1 or key in seen:
            return False
        seen.add(key)
        rule = db.scalar(select(LegalRuleVersion).where(
            LegalRuleVersion.rule_id == rule_id,
            LegalRuleVersion.version == version,
        ))
        if rule is None:
            return False
        evaluation_id = str(evaluation.get("rule_evaluation_id") or "")
        if not evaluation_id or evaluation_id in seen_evaluations:
            return False
        seen_evaluations.add(evaluation_id)
        persisted = db.get(RuleEvaluation, evaluation_id)
        if (
            persisted is None
            or persisted.case_id != case.id
            or persisted.rule_version_id != rule.id
        ):
            return False
        if not professionally_approved(rule):
            return False
    return True


def participant_substantive_output_allowed(db: Session, case: Case) -> bool:
    """Synthetic output works; every other mode requires the substantive gate."""
    if case.mode == "SYNTHETIC":
        return True
    if case.mode != "PRIVATE_REAL_BETA":
        return False
    return substantive_legal_output_approved(db, case)
