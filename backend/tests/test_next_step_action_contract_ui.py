from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def _fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _c04_case(client, *, order_date: str, additional_requested=None):
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C04"
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": order_date,
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
    }
    if additional_requested is not None:
        facts["purchase.additional_delivery_period_requested"] = additional_requested
    for key, value in facts.items():
        _fact(client, case_id, key, value)
    return case_id


def test_waiting_diagnosis_exposes_wait_action_not_claim_preparation(client):
    case_id = _c04_case(client, order_date="2026-09-01")
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "MEDIUM"
    assert diagnosis.json()["next_action"] == "WAIT_UNTIL_DELIVERY_DUE"

    case = client.get(f"/api/cases/{case_id}")
    assert case.status_code == 200
    body = case.json()
    assert body["status"] == "DIAGNOSED"
    current = next(item for item in body["actions"] if item["id"] == body["current_action_id"])
    assert current["type"] == "WAIT_UNTIL_DELIVERY_DUE"


def test_action_that_really_requires_outbound_preparation_remains_preparable(client):
    case_id = _c04_case(client, order_date="2026-07-01", additional_requested=False)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH"
    assert diagnosis.json()["next_action"] == "GIVE_ADDITIONAL_DELIVERY_PERIOD"


def test_next_step_ui_gates_prepare_button_by_current_action_not_viability_alone():
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    assert "function currentAction()" in script
    assert "function isPreparableAction(type)" in script
    assert "type.startsWith('PREPARE_')" in script
    assert "GIVE_ADDITIONAL_DELIVERY_PERIOD" in script
    assert "SEND_WITHDRAWAL_NOTICE" in script
    assert "if (isPreparableAction(type) && ['HIGH', 'MEDIUM'].includes(currentDecision?.viability))" in script
    assert "if (type.startsWith('WAIT_'))" in script
    assert "Todavía no toca enviar una nueva acción" in script
    assert "CHOOSE_" in script
    assert "RETURN_GOODS_WITH_PROOF" in script


def test_next_step_action_contract_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    source = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
