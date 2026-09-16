from sqlalchemy import func, select

from app.models import Action, Case, Decision


def test_claimant_cannot_replay_missing_information_diagnosis_without_new_fact(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None

    decision = Decision(
        case_id=case.id,
        viability="INSUFFICIENT_INFORMATION",
        scope_status="SUPPORTED",
        economic_value=None,
        claimable_amount=None,
        worth_pursuing="UNKNOWN",
        professional_review_required=False,
        reasoning_summary="Synthetic incomplete diagnosis for HTTP replay regression.",
        counterarguments_snapshot=[],
        rule_evaluations_json=[],
    )
    db.add(decision)
    db.flush()
    action = Action(case_id=case.id, type="ASK_MORE_INFORMATION", status="OPEN", payload_json={})
    db.add(action)
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id
    case.status = "NEEDS_INFORMATION"
    db.commit()

    before_decisions = db.scalar(
        select(func.count()).select_from(Decision).where(Decision.case_id == case_id)
    )
    before_actions = db.scalar(
        select(func.count()).select_from(Action).where(Action.case_id == case_id)
    )

    replay = client.post(f"/api/cases/{case_id}/diagnose")
    assert replay.status_code == 409, replay.text
    assert replay.json()["detail"] == "Update the case facts before requesting a new diagnosis"

    db.expire_all()
    refreshed = db.get(Case, case_id)
    assert refreshed is not None
    assert refreshed.status == "NEEDS_INFORMATION"
    assert refreshed.current_decision_id == decision.id
    assert refreshed.current_action_id == action.id
    assert db.get(Action, action.id).status == "OPEN"
    assert db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case_id)) == before_decisions
    assert db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)) == before_actions


def test_new_claimant_fact_reopens_intake_and_allows_diagnosis_request(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None
    case.status = "NEEDS_INFORMATION"
    db.commit()

    fact = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "electricity.addon.keep_requested",
            "value": False,
            "state": "confirmed",
            "materiality": "critical",
            "user_confirmed": True,
        },
    )
    assert fact.status_code == 200, fact.text

    db.expire_all()
    reopened = db.get(Case, case_id)
    assert reopened is not None
    assert reopened.status == "INTAKE"

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code != 409, diagnosis.text
