from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_case_communication_history_combines_verified_submission_and_company_response(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-16",
            "channel": "web",
            "reference_number": "REF-123",
        },
    )
    assert submitted.status_code == 200

    response_text = "Denegamos la devolución porque el contrato de mantenimiento es independiente."
    received = client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": response_text},
    )
    assert received.status_code == 200

    history = client.get(f"/api/cases/{case_id}/communications")
    assert history.status_code == 200
    body = history.json()
    assert body["case_id"] == case_id
    assert len(body["communications"]) == 2

    outbound, inbound = body["communications"]
    assert outbound == {
        "direction": "OUTBOUND",
        "kind": "CLAIM_SUBMISSION",
        "channel": "web",
        "reference_number": "REF-123",
        "body": None,
        "occurred_on": "2026-09-16",
        "recorded_at": outbound["recorded_at"],
    }
    assert outbound["recorded_at"]

    assert inbound["direction"] == "INBOUND"
    assert inbound["kind"] == "COMPANY_RESPONSE"
    assert inbound["channel"] == "user_paste"
    assert inbound["body"] == response_text
    assert inbound["occurred_on"]
    assert "payload" not in inbound
    assert "event_type" not in inbound


def test_communication_history_uses_existing_case_access_gate(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compra online no entregada"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    blocked = client.get(
        f"/api/cases/{case_id}/communications",
        headers={"X-Case-Token": "wrong-token"},
    )
    assert blocked.status_code == 404
    assert blocked.json()["detail"] == "Case not found"


def test_communication_history_ui_is_modular_and_avoids_browser_storage():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "communication_history.js").read_text(encoding="utf-8")
    assert "/demo/communication_history.js" in loader
    assert "/communications" in script
    assert "Reclamaciones y respuestas registradas" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_communication_history_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "communication_history.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
