def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={"key": key, "value": value, "state": state, "user_confirmed": user_confirmed},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_e03(client, message="Me han cambiado de compañía de luz sin mi consentimiento"):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertical"] == "electricity"
    assert body["family"] == "E03"
    assert body["title"] == "Cambio de comercializadora sin consentimiento"
    return body["id"]


def fill_e03(
    client,
    cid,
    *,
    switch_date="2026-09-01",
    cups_correct=True,
    consent=False,
    proof_status="not_provided",
    amount=0.0,
    identity_theft=False,
):
    facts = {
        "electricity.switch_effective_date": switch_date,
        "electricity.previous_supplier": "Comercializadora anterior",
        "electricity.incoming_supplier": "Comercializadora entrante",
        "electricity.possible_identity_theft": identity_theft,
        "electricity.switch_cups_correct": cups_correct,
        "electricity.express_consent_given": consent,
        "electricity.consent_evidence_status": proof_status,
        "electricity.unsolicited_supply_amount_paid": amount,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)


def test_e03_no_consent_restores_previous_supplier_and_refunds_paid_amount(client):
    cid = create_e03(client)
    fill_e03(client, cid, amount=43.20)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 43.20
    assert body["next_action"] == "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION"
    assert "RESTORE_PREVIOUS_SUPPLIER" in body["remedies"]
    assert any(item.get("basis") == "RD88_2026_18_5" for item in body["burden_of_proof"])

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "E03_UNAUTHORIZED_SWITCH_RESTORATION"
    assert payload["amount"] == 43.20
    assert "51.3" in payload["text"]


def test_e03_wrong_cups_is_actionable_even_if_consent_record_exists(client):
    cid = create_e03(client, "Han cambiado mi contrato de luz usando un CUPS equivocado")
    fill_e03(
        client,
        cid,
        cups_correct=False,
        consent=True,
        proof_status="valid_durable_proof",
        amount=0.0,
    )
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION"
    assert "CUPS incorrecto" in body["reasoning_summary"]


def test_e03_valid_consent_and_correct_cups_defeats_this_family(client):
    cid = create_e03(client)
    fill_e03(
        client,
        cid,
        cups_correct=True,
        consent=True,
        proof_status="valid_durable_proof",
        amount=0.0,
    )
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_VALID_CONSENT"
    assert body["claimable_amount"] == 0.0


def test_e03_identity_theft_is_never_auto_resolved(client):
    cid = create_e03(client)
    fill_e03(client, cid, identity_theft=True)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["scope_status"] == "FRAUD_OR_IDENTITY_RISK"
    assert body["next_action"] == "HUMAN_REVIEW_IDENTITY_THEFT"
    reviews = client.get(f"/api/cases/{cid}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "OPEN"


def test_e03_before_current_regime_goes_to_legacy_review(client):
    cid = create_e03(client)
    fill_e03(client, cid, switch_date="2026-02-11")
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["scope_status"] == "LEGACY_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_LEGACY"


def test_e03_supplier_consent_argument_reanalyzes_case(client):
    cid = create_e03(client)
    fill_e03(client, cid, amount=25.0)
    assert client.post(f"/api/cases/{cid}/diagnose").json()["viability"] == "HIGH"

    response = client.post(
        f"/api/cases/{cid}/responses",
        json={"text": "Consta su consentimiento expreso y disponemos de una grabación de consentimiento para el cambio."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["type"] == "DENIAL"
    assert body["updated_diagnosis"] is not None
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"
    assert any(
        item["type"] == "SUPPLIER_ASSERTS_EXPRESS_CONSENT"
        for item in body["updated_diagnosis"]["counterarguments"]
    )


def test_e03_electricity_submission_keeps_sector_complaint_deadline_path(client):
    cid = create_e03(client)
    fill_e03(client, cid, amount=10.0)
    assert client.post(f"/api/cases/{cid}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{cid}/prepare-claim").status_code == 200
    response = client.post(
        f"/api/cases/{cid}/submission",
        json={"submitted_on": "2026-09-15", "channel": "web"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deadline"] is not None
    assert response.json()["deadline_status"] in {"ACTIVE", "PROVISIONAL_CALENDAR"}
