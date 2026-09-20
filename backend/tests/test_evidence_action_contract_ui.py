from pathlib import Path
import shutil
import subprocess
import tempfile

from app.action_contract import action_kind


STATIC = Path(__file__).parents[1] / "app" / "static"


EVIDENCE_ACTIONS = {
    "REQUEST_CONTRACT_OR_OFFER_EVIDENCE",
    "REQUEST_DUPLICATE_CHARGE_EVIDENCE",
    "REQUEST_CONSENT_EVIDENCE",
    "REQUEST_CHARGE_EVIDENCE",
}


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_document_evidence_actions_have_their_own_operational_kind():
    assert {action: action_kind(action) for action in EVIDENCE_ACTIONS} == {
        action: "evidence_input" for action in EVIDENCE_ACTIONS
    }
    assert action_kind("REQUEST_MATERIAL_FACT") == "guided_input"
    assert action_kind("REQUEST_ADDITIONAL_PERIOD_DEADLINE") == "guided_input"


def test_e02b_unverified_duplicate_charges_route_to_evidence_not_another_fact_question(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "E02-B"

    _fact(client, case_id, "electricity.billing.same_debt", True)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {"amount": 74.30, "evidence_verified": False},
                {"amount": 74.30, "evidence_verified": False},
            ]
        },
    )
    assert charges.status_code == 200, charges.text

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "REQUEST_DUPLICATE_CHARGE_EVIDENCE"
    assert action_kind(diagnosis.json()["next_action"]) == "evidence_input"

    body = client.get(f"/api/cases/{case_id}").json()
    current = next(item for item in body["actions"] if item["id"] == body["current_action_id"])
    assert current["type"] == "REQUEST_DUPLICATE_CHARGE_EVIDENCE"


def test_next_step_ui_routes_evidence_actions_to_documentation_panel():
    source = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    for action in EVIDENCE_ACTIONS:
        assert action in source
    assert "function needsDocumentEvidence(type)" in source
    assert "Aporta la evidencia que falta" in source
    assert "Ir a documentación" in source
    assert "document.getElementById('documentPanel')" in source
    assert "if (!type || needsDocumentEvidence(type)) return false" in source


def test_evidence_action_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    source = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
