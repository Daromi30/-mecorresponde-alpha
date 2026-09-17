import pytest
from sqlalchemy import func, select

from app import services_v2 as svc
from app.models import Action, Case, Decision, Fact


def _counts(db, case_id: str) -> tuple[int, int]:
    decisions = int(
        db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case_id)) or 0
    )
    actions = int(
        db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)) or 0
    )
    return decisions, actions


def _fact_count(db, case_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case_id)) or 0)


def test_core_reanalysis_rejects_pending_current_action_without_mutation(db):
    case = Case(
        status="REANALYZING",
        vertical="electricity",
        family="E04-B",
        title="Protected reanalysis replay",
    )
    db.add(case)
    db.flush()
    pending = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="OPEN",
        payload_json={"phase": "REVIEW_PENDING"},
    )
    db.add(pending)
    db.flush()
    case.current_action_id = pending.id
    db.commit()

    before = _counts(db, case.id)
    with pytest.raises(ValueError, match="Complete the current action before reanalyzing the case"):
        svc.diagnose(db, case)

    db.expire_all()
    refreshed = db.get(Case, case.id)
    stored_action = db.get(Action, pending.id)
    assert refreshed is not None
    assert refreshed.status == "REANALYZING"
    assert refreshed.current_action_id == pending.id
    assert stored_action is not None and stored_action.status == "OPEN"
    assert _counts(db, case.id) == before


def test_core_reanalysis_allows_transition_after_previous_action_completed(db):
    case = Case(
        status="REANALYZING",
        vertical="electricity",
        family="E04-B",
        title="Completed review can reanalyze",
    )
    db.add(case)
    db.flush()
    previous = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="COMPLETED",
        payload_json={"phase": "REVIEW_DONE"},
    )
    db.add(previous)
    db.flush()
    case.current_action_id = previous.id
    db.commit()

    result, decision, action = svc.diagnose(db, case)

    assert result.missing_facts
    assert decision.case_id == case.id
    assert action.case_id == case.id
    assert action.id != previous.id
    assert case.current_decision_id == decision.id
    assert case.current_action_id == action.id
    assert case.status == "NEEDS_INFORMATION"
    assert db.get(Action, previous.id).status == "COMPLETED"


def test_claimant_cannot_trigger_diagnosis_while_protected_reanalysis_is_pending(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None

    pending = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="COMPLETED",
        payload_json={"phase": "REVIEW_DONE"},
    )
    db.add(pending)
    db.flush()
    case.current_action_id = pending.id
    case.status = "REANALYZING"
    db.commit()

    before = _counts(db, case_id)
    attempted = client.post(f"/api/cases/{case_id}/diagnose")
    assert attempted.status_code == 409, attempted.text
    assert attempted.json()["detail"] == "This case is being reanalyzed through the protected review workflow"

    db.expire_all()
    refreshed = db.get(Case, case_id)
    assert refreshed is not None
    assert refreshed.status == "REANALYZING"
    assert refreshed.current_action_id == pending.id
    assert _counts(db, case_id) == before


def test_claimant_cannot_mutate_facts_while_protected_reanalysis_is_pending(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None

    previous = Action(
        case_id=case.id,
        type="HUMAN_REVIEW_TECHNICAL",
        status="COMPLETED",
        payload_json={"phase": "REVIEW_DONE"},
    )
    db.add(previous)
    db.flush()
    case.current_action_id = previous.id
    case.status = "REANALYZING"
    db.commit()

    before_facts = _fact_count(db, case_id)
    attempted = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "electricity.addon.keep_requested",
            "value": True,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert attempted.status_code == 409, attempted.text
    assert "locked in the current phase" in attempted.json()["detail"]

    db.expire_all()
    refreshed = db.get(Case, case_id)
    assert refreshed is not None
    assert refreshed.status == "REANALYZING"
    assert refreshed.current_action_id == previous.id
    assert _fact_count(db, case_id) == before_facts
