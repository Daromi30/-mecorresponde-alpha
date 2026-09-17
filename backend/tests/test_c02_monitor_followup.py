from sqlalchemy import select

from app.models import Action, Case


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _monitor_case(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Compré una lavadora, ya la repararon y ahora parece funcionar"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C02"
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Lavadora",
        "purchase.delivery_date": "2026-02-10",
        "purchase.price": 520.0,
        "purchase.conformity_attempts": 1,
        "purchase.lack_after_conformity_attempt": False,
        "purchase.repair_still_pending": False,
        "purchase.seller_declared_will_not_conform": False,
    }.items():
        _fact(client, case_id, key, value)
    return case_id


def test_monitor_conformity_reopens_the_changed_fact_and_resumes_c02(client, db):
    case_id = _monitor_case(client)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "MONITOR_CONFORMITY"
    old_action_id = diagnosis.json()["action_id"]

    question = client.get(f"/api/cases/{case_id}/next-question")
    assert question.status_code == 200, question.text
    assert question.json() == {
        "done": False,
        "question": "¿Ha vuelto a aparecer una falta o problema después de la reparación o sustitución?",
        "field": "purchase.lack_after_conformity_attempt",
        "input_type": "boolean",
    }

    changed = _fact(client, case_id, "purchase.lack_after_conformity_attempt", True)
    assert changed["next_question"]["field"] == "purchase.same_origin_after_repair"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "INTAKE"
    assert case.current_action_id is None
    assert case.current_decision_id is None
    old_action = db.get(Action, old_action_id)
    assert old_action is not None
    assert old_action.status == "SUPERSEDED"
    assert old_action.completed_at is not None

    _fact(client, case_id, "purchase.same_origin_after_repair", False)
    choice = _fact(client, case_id, "purchase.preferred_secondary_remedy", "price_reduction")
    assert choice["next_question"]["done"] is True

    rediagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert rediagnosis.status_code == 200, rediagnosis.text
    assert rediagnosis.json()["next_action"] == "PREPARE_C02_PRICE_REDUCTION"
    assert rediagnosis.json()["viability"] in {"HIGH", "MEDIUM"}

    db.expire_all()
    current = db.get(Action, db.get(Case, case_id).current_action_id)
    assert current is not None
    assert current.type == "PREPARE_C02_PRICE_REDUCTION"
    assert current.status == "OPEN"


def test_monitor_followup_does_not_create_duplicate_actions_until_fact_changes(client, db):
    case_id = _monitor_case(client)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200
    old_action_id = diagnosis.json()["action_id"]

    first = client.get(f"/api/cases/{case_id}/next-question")
    second = client.get(f"/api/cases/{case_id}/next-question")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    db.expire_all()
    actions = db.scalars(select(Action).where(Action.case_id == case_id)).all()
    assert len(actions) == 1
    assert actions[0].id == old_action_id
    assert actions[0].status == "OPEN"
