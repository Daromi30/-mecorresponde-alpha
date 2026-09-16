from sqlalchemy import func, select

from app.models import Action, Case, Decision


def _seed_diagnosed_case(client, db):
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
        viability="HIGH",
        scope_status="SUPPORTED",
        economic_value=25.0,
        claimable_amount=25.0,
        worth_pursuing="YES",
        professional_review_required=False,
        reasoning_summary="Synthetic current diagnosis for lifecycle guard regression.",
        counterarguments_snapshot=[],
        rule_evaluations_json=[],
    )
    db.add(decision)
    db.flush()
    action = Action(
        case_id=case.id,
        type="PREPARE_CLAIM",
        status="OPEN",
        payload_json={},
    )
    db.add(action)
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id
    case.status = "DIAGNOSED"
    db.commit()
    return case_id, decision.id, action.id


def test_diagnosis_replay_from_diagnosed_phase_fails_without_mutation(client, db):
    case_id, decision_id, action_id = _seed_diagnosed_case(client, db)

    before_decisions = db.scalar(
        select(func.count()).select_from(Decision).where(Decision.case_id == case_id)
    )
    before_actions = db.scalar(
        select(func.count()).select_from(Action).where(Action.case_id == case_id)
    )

    replay = client.post(f"/api/cases/{case_id}/diagnose")
    assert replay.status_code == 422, replay.text
    assert replay.json()["detail"] == "The case is not in a phase that permits a new diagnosis"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "DIAGNOSED"
    assert case.current_decision_id == decision_id
    assert case.current_action_id == action_id
    assert db.get(Action, action_id).status == "OPEN"

    after_decisions = db.scalar(
        select(func.count()).select_from(Decision).where(Decision.case_id == case_id)
    )
    after_actions = db.scalar(
        select(func.count()).select_from(Action).where(Action.case_id == case_id)
    )
    assert after_decisions == before_decisions
    assert after_actions == before_actions
