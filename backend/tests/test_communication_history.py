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
            "submitted_on": "2026-09-10",
            "channel": "web_form",
            "reference_number": "REF-123",
        },
    )
    assert submitted.status_code == 200

    response_text = "Denegamos la devolución porque el contrato de mantenimiento es independiente."
    received = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": response_text,
            "received_on": "2026-09-14",
            "channel": "email",
            "reference_number": "RESP-88",
        },
    )
    assert received.status_code == 200, received.text

    history = client.get(f"/api/cases/{case_id}/communications")
    assert history.status_code == 200
    body = history.json()
    assert body["case_id"] == case_id
    assert len(body["communications"]) == 2

    outbound, inbound = body["communications"]
    assert outbound == {
        "direction": "OUTBOUND",
        "kind": "CLAIM_SUBMISSION",
        "channel": "web_form",
        "reference_number": "REF-123",
        "body": None,
        "occurred_on": "2026-09-10",
        "recorded_at": outbound["recorded_at"],
    }
    assert outbound["recorded_at"]

    assert inbound["direction"] == "INBOUND"
    assert inbound["kind"] == "COMPANY_RESPONSE"
    assert inbound["channel"] == "email"
    assert inbound["reference_number"] == "RESP-88"
    assert inbound["body"] == response_text
    assert inbound["occurred_on"] == "2026-09-14"
    assert inbound["recorded_at"]
    assert "payload" not in inbound
    assert "event_type" not in inbound


def test_legacy_pasted_response_does_not_turn_processing_day_into_verified_receipt_day(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    response = client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": "Rechazamos su reclamación porque el servicio es independiente."},
    )
    assert response.status_code == 200

    history = client.get(f"/api/cases/{case_id}/communications").json()
    inbound = history["communications"][0]
    assert inbound["direction"] == "INBOUND"
    assert inbound["occurred_on"] is None
    assert inbound["channel"] is None
    assert inbound["reference_number"] is None
    assert inbound["recorded_at"]


def test_response_date_may_remain_unknown_without_fabrication(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compra online no entregada"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "No podemos estimar su solicitud en este momento.",
            "received_on": None,
            "channel": "unknown",
            "reference_number": None,
        },
    )
    assert response.status_code == 200, response.text
    inbound = client.get(f"/api/cases/{case_id}/communications").json()["communications"][0]
    assert inbound["occurred_on"] is None
    assert inbound["channel"] == "unknown"


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


def test_communication_history_ui_loads_response_evidence_without_browser_storage():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    history = (STATIC / "communication_history.js").read_text(encoding="utf-8")
    response = (STATIC / "response_evidence.js").read_text(encoding="utf-8")
    assert "/demo/communication_history.js" in loader
    assert "/demo/response_evidence.js" in loader
    assert "/communications" in history
    assert "/responses/evidenced" in response
    assert "responseReceivedOn" in response
    assert "responseChannel" in response
    assert "responseReference" in response
    assert "si no la conoces, la dejamos sin confirmar" in response
    for script in (history, response):
        assert "localStorage" not in script
        assert "sessionStorage" not in script


def test_communication_history_and_response_evidence_javascript_parse_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ("communication_history.js", "response_evidence.js"):
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"