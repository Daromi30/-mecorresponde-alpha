import pytest
from sqlalchemy import func, select

from app import services_v2 as svc
from app.models import Action, Case, Decision


def test_core_diagnosis_rejects_unchanged_missing_information_snapshot_without_mutation(db):
    case = Case(
        status="NEEDS_INFORMATION",
        vertical="electricity",
        family="E04-B",
        title="Missing-information replay guard",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    before_decisions = db.scalar(
        select(func.count()).select_from(Decision).where(Decision.case_id == case.id)
    )
    before_actions = db.scalar(
        select(func.count()).select_from(Action).where(Action.case_id == case.id)
    )

    with pytest.raises(ValueError, match="not in a phase that permits a new diagnosis"):
        svc.diagnose(db, case)

    db.expire_all()
    refreshed = db.get(Case, case.id)
    assert refreshed is not None
    assert refreshed.status == "NEEDS_INFORMATION"
    assert refreshed.current_decision_id is None
    assert refreshed.current_action_id is None
    assert db.scalar(
        select(func.count()).select_from(Decision).where(Decision.case_id == case.id)
    ) == before_decisions
    assert db.scalar(
        select(func.count()).select_from(Action).where(Action.case_id == case.id)
    ) == before_actions


def test_core_diagnosis_allows_same_case_after_snapshot_is_reopened_to_intake(db):
    case = Case(
        status="INTAKE",
        vertical="electricity",
        family="E04-B",
        title="Fresh intake diagnosis",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    result, decision, action = svc.diagnose(db, case)

    assert result.missing_facts
    assert decision.case_id == case.id
    assert action.case_id == case.id
    assert case.status == "NEEDS_INFORMATION"
    assert case.current_decision_id == decision.id
    assert case.current_action_id == action.id
