from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"


def _fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_omitted_charge_evidence_never_defaults_to_verified(client):
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
        json={"charges": [{"amount": 42.5}, {"amount": 42.5}]},
    )
    assert charges.status_code == 200, charges.text

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "INSUFFICIENT_INFORMATION"
    assert body["claimable_amount"] is None
    assert "second_verified_charge" in body["missing_facts"]


def test_explicitly_confirmed_charge_evidence_can_be_used_by_the_motor(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    case_id = created.json()["id"]
    _fact(client, case_id, "electricity.billing.same_debt", True)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {"amount": 42.5, "charged_at": "2026-09-10", "evidence_verified": True},
                {"amount": 42.5, "charged_at": "2026-09-11", "evidence_verified": True},
            ]
        },
    )
    assert charges.status_code == 200, charges.text
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 42.5


def test_browser_charge_editor_uses_schema_field_and_explicit_evidence_confirmation():
    script = (STATIC / "guided_question_inputs.js").read_text(encoding="utf-8")
    assert "charged_at" in script
    assert "charged_on" not in script
    assert "chargeEvidence" in script
    assert "evidence_verified: Boolean" in script
    assert "factura, recibo o movimiento bancario" in script
