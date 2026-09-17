from datetime import timedelta
from pathlib import Path

from app.calendar_clock import spain_today
from app.models import Action, Case


STATIC = Path(__file__).parents[1] / "app" / "static"


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _build_return_pending_c05(client) -> str:
    today = spain_today()
    created = client.post(
        "/api/cases",
        json={"message": "Compré unos auriculares online, desistí y tengo que devolver el producto"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C05"

    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": (today - timedelta(days=5)).isoformat(),
        "purchase.amount_paid": 100.0,
        "purchase.premium_delivery_extra": 0.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": (today - timedelta(days=2)).isoformat(),
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": False,
        "purchase.return_sent": False,
    }
    for key, value in facts.items():
        _fact(client, case_id, key, value)
    return case_id


def test_return_goods_external_step_can_be_completed_through_guided_facts(client, db):
    case_id = _build_return_pending_c05(client)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    initial = diagnosis.json()
    assert initial["next_action"] == "RETURN_GOODS_WITH_PROOF"
    old_action_id = initial["action_id"]

    question = client.get(f"/api/cases/{case_id}/next-question")
    assert question.status_code == 200, question.text
    assert question.json() == {
        "done": False,
        "question": "¿Ya has devuelto o enviado de vuelta el producto?",
        "field": "purchase.return_sent",
        "input_type": "boolean",
    }

    returned = _fact(client, case_id, "purchase.return_sent", True)
    assert returned["next_question"]["field"] == "purchase.return_proof_available"
    assert returned["next_question"]["input_type"] == "boolean"

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

    proof = _fact(client, case_id, "purchase.return_proof_available", True)
    assert proof["next_question"]["done"] is True

    reanalysis = client.post(f"/api/cases/{case_id}/diagnose")
    assert reanalysis.status_code == 200, reanalysis.text
    assert reanalysis.json()["next_action"] == "WAIT_WITHDRAWAL_REFUND_PERIOD"
    assert reanalysis.json()["rule_result"] == "REFUND_PERIOD_RUNNING"


def test_return_goods_next_step_card_opens_guided_update_instead_of_diagnosis_only():
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    assert "type === 'RETURN_GOODS_WITH_PROOF'" in script
    assert "button: 'Actualizar devolución'" in script
    return_block = script.split("if (type === 'RETURN_GOODS_WITH_PROOF')", 1)[1].split("if (type.startsWith('EXPLAIN_')", 1)[0]
    assert "document.getElementById('questionArea')" in return_block
    assert "document.getElementById('diagnosisCard')" not in return_block
