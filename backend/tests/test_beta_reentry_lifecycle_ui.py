from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_ready_to_submit_case_serializes_exact_prepared_payload_for_reentry(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        _fact(client, case_id, key, value)

    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                }
            ]
        },
    )
    assert charges.status_code == 200, charges.text
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200

    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    prepared_body = prepared.json()

    reopened = client.get(f"/api/cases/{case_id}")
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body["status"] == "READY_TO_SUBMIT"
    current = next(action for action in body["actions"] if action["id"] == body["current_action_id"])
    assert current["type"] == "SUBMIT_INITIAL_CLAIM"
    assert current["status"] == "READY"
    assert current["payload"]["text"] == prepared_body["text"]
    assert current["payload"]["legal_basis"] == prepared_body["legal_basis"]
    assert current["payload"]["claim_type"] == prepared_body["claim_type"]


def test_phase_ui_restores_prepared_claim_and_hides_stale_action_cards():
    script = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    assert "status === 'READY_TO_SUBMIT'" in script
    assert "action?.type !== 'SUBMIT_INITIAL_CLAIM'" in script
    assert "action?.status !== 'READY'" in script
    assert "renderClaim(action.payload)" in script
    assert "setCardVisible('claimCard', status === 'READY_TO_SUBMIT')" in script
    assert "setCardVisible('responseCard', status === 'WAITING_RESPONSE')" in script
    assert "setCardVisible('outcomeCard', status === 'RESOLVED_PENDING_EXECUTION')" in script


def test_phase_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
