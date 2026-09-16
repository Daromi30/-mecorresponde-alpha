from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def create_case(client, message="Me cambié de compañía de luz y me siguen cobrando un mantenimiento"):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def put_fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def complete_e04b(client, case_id):
    put_fact(client, case_id, "electricity.supply_end_date", "2026-06-03")
    put_fact(client, case_id, "electricity.addon.identity", "Protección Hogar")
    put_fact(client, case_id, "electricity.addon.ever_contracted", True)
    put_fact(client, case_id, "electricity.addon.contracted_with_supply", True)
    put_fact(client, case_id, "electricity.addon.keep_requested", False)
    response = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    )
    assert response.status_code == 200


def test_timeline_tracks_resolution_milestones_without_internal_payloads(client):
    created = create_case(client)
    case_id = created["id"]

    initial = client.get(f"/api/cases/{case_id}/timeline")
    assert initial.status_code == 200
    assert [event["type"] for event in initial.json()["events"]] == ["CASE_OPENED"]

    complete_e04b(client, case_id)
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-15", "channel": "web", "reference_number": "TEST-123"},
    ).status_code == 200
    accepted = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-16",
            "channel": "email",
            "reference_number": "RESP-123",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["analysis"]["type"] == "ACCEPTANCE"
    resolved = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 8.99,
            "verified_by_user": True,
            "resolved_on": "2026-09-16",
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert resolved.status_code == 200, resolved.text

    response = client.get(f"/api/cases/{case_id}/timeline")
    assert response.status_code == 200
    body = response.json()
    types = [event["type"] for event in body["events"]]
    assert types[0] == "CASE_OPENED"
    assert "DIAGNOSIS_UPDATED" in types
    assert "CLAIM_SUBMITTED" in types
    assert "CLAIM_ACCEPTED_PENDING_EXECUTION" in types
    assert "RESOLUTION_VERIFIED" in types
    assert body["current_status"] == "RESOLVED"

    # The public timeline is an allowlisted summary, never the raw internal audit payload.
    text = response.text
    assert "TEST-123" not in text
    assert "RESP-123" not in text
    assert "payload_json" not in text
    assert "rule_evaluations_json" not in text


def test_timeline_respects_case_access_isolation(client):
    first = create_case(client, "Me han cobrado dos veces la misma factura de luz")
    second = create_case(client, "Compré un pedido online y no me ha llegado")
    blocked = client.get(
        f"/api/cases/{first['id']}/timeline",
        headers={"X-Case-Token": second["access_token"]},
    )
    assert blocked.status_code == 404
    assert client.get(
        f"/api/cases/{first['id']}/timeline",
        headers={"X-Case-Token": first["access_token"]},
    ).status_code == 200


def test_timeline_ui_is_loaded_and_javascript_parses():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_timeline.js").read_text(encoding="utf-8")
    assert "/demo/case_timeline.js" in loader
    assert "mcr-case-timeline" in loader
    assert "/timeline" in script
    assert "Recorrido del expediente" in script
    assert "registros técnicos internos" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script

    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "case_timeline.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
