from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def create_submitted_e04b(client, submitted_on="2026-09-10", reference="REF-123"):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        assert client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        ).status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    ).status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": submitted_on,
            "channel": "web_form",
            "reference_number": reference,
        },
    )
    assert submitted.status_code == 200, submitted.text
    return case_id


def test_case_communication_history_combines_verified_submission_and_company_response(client):
    case_id = create_submitted_e04b(client)

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


def test_legacy_pasted_response_route_is_closed_in_favor_of_evidenced_response(client):
    case_id = create_submitted_e04b(client)
    response = client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": "Rechazamos su reclamación porque el servicio es independiente."},
    )
    assert response.status_code == 409
    assert "evidenced" in response.json()["detail"]


def test_response_date_may_remain_unknown_without_fabrication(client):
    case_id = create_submitted_e04b(client)

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
    inbound = client.get(f"/api/cases/{case_id}/communications").json()["communications"][1]
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
