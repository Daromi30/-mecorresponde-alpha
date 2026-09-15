def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={
            "key": key,
            "value": value,
            "state": state,
            "user_confirmed": user_confirmed,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_classifier_routes_e03_unauthorized_switch(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me han cambiado de compañía de luz sin mi consentimiento"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vertical"] == "electricity"
    assert body["family"] == "E03"


def test_classifier_routes_e05_termination_penalty(client):
    response = client.post(
        "/api/cases",
        json={"message": "Endesa me cobra una penalización por darme de baja de la luz"},
    )
    assert response.status_code == 200
    assert response.json()["family"] == "E05"


def build_e03_case(client, *, cups_correct=True, consent=False, proof="not_provided", amount=42.50):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cambiado de compañía de luz sin mi consentimiento"},
    )
    assert created.status_code == 200
    cid = created.json()["id"]
    facts = {
        "electricity.switch_effective_date": "2026-09-01",
        "electricity.previous_supplier": "Comercializadora anterior",
        "electricity.incoming_supplier": "Comercializadora nueva",
        "electricity.possible_identity_theft": False,
        "electricity.switch_cups_correct": cups_correct,
        "electricity.express_consent_given": consent,
        "electricity.consent_evidence_status": proof,
        "electricity.unsolicited_supply_amount_paid": amount,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_e03_no_consent_restores_previous_contract_and_refund(client):
    cid = build_e03_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 42.50
    assert body["next_action"] == "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION"
    assert "RESTORE_PREVIOUS_SUPPLIER" in body["remedies"]
    assert any(item.get("basis") == "RD88_2026_18_5" for item in body["burden_of_proof"])

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "E03_UNAUTHORIZED_SWITCH_RESTORATION"
    assert payload["amount"] == 42.50
    assert "51.3" in payload["text"]


def test_e03_wrong_cups_remains_actionable_even_with_valid_consent_record(client):
    cid = build_e03_case(client, cups_correct=False, consent=True, proof="valid_durable_proof", amount=0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION"
    assert "CUPS incorrecto" in body["reasoning_summary"]


def test_e03_company_consent_assertion_reduces_confidence_and_reanalyzes(client):
    cid = build_e03_case(client)
    assert client.post(f"/api/cases/{cid}/diagnose").json()["viability"] == "HIGH"
    response = client.post(
        f"/api/cases/{cid}/responses",
        json={"text": "Consta su consentimiento expreso en una grabación de consentimiento."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["type"] == "DENIAL"
    assert body["updated_diagnosis"] is not None
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"


def test_e03_legacy_switch_goes_to_human_review(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambiaron de compañía de luz sin permiso"},
    ).json()
    cid = created["id"]
    post_fact(client, cid, "electricity.switch_effective_date", "2026-02-01")
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"
    reviews = client.get(f"/api/cases/{cid}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "OPEN"


def build_e05_case(client, *, fixed=False, renewed=False, penalty=89.0, loss_proof=None, termination="2026-09-01"):
    created = client.post(
        "/api/cases",
        json={"message": "Endesa me cobra una penalización por darme de baja de la luz"},
    )
    assert created.status_code == 200
    cid = created.json()["id"]
    facts = {
        "electricity.termination_date": termination,
        "electricity.contract_holder_is_natural_person": True,
        "electricity.tariff_is_2_0td": True,
        "electricity.termination_penalty_charged": penalty,
        "electricity.contract_is_fixed_price": fixed,
        "electricity.first_annual_renewal_already_occurred": renewed,
    }
    if loss_proof is not None:
        facts["electricity.supplier_direct_loss_proof_status"] = loss_proof
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_e05_non_fixed_contract_penalty_is_challenged(client):
    cid = build_e05_case(client, fixed=False, renewed=False, penalty=89.0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 89.0
    assert body["next_action"] == "PREPARE_INVALID_TERMINATION_PENALTY_CLAIM"

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "E05_TERMINATION_PENALTY_CHALLENGE"
    assert claim.json()["amount"] == 89.0
    assert "28.3" in claim.json()["text"]


def test_e05_after_first_renewal_penalty_is_challenged(client):
    cid = build_e05_case(client, fixed=True, renewed=True, penalty=60.0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose").json()
    assert diagnosis["viability"] == "HIGH"
    assert diagnosis["claimable_amount"] == 60.0


def test_e05_fixed_price_before_first_renewal_requests_supplier_proof(client):
    cid = build_e05_case(client, fixed=True, renewed=False, penalty=75.0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["viability"] == "MEDIUM"
    assert body["claimable_amount"] is None
    assert body["next_action"] == "REQUEST_PENALTY_JUSTIFICATION"
    assert any(item.get("on") == "supplier" for item in body["burden_of_proof"])

    request = client.post(f"/api/cases/{cid}/prepare-claim")
    assert request.status_code == 200, request.text
    assert request.json()["claim_type"] == "E05_REQUEST_PENALTY_JUSTIFICATION"
    assert request.json()["amount"] == 0.0


def test_e05_no_direct_loss_proof_opens_full_penalty_challenge(client):
    cid = build_e05_case(
        client, fixed=True, renewed=False, penalty=75.0,
        loss_proof="none_or_not_provided",
    )
    diagnosis = client.post(f"/api/cases/{cid}/diagnose").json()
    assert diagnosis["viability"] == "HIGH"
    assert diagnosis["claimable_amount"] == 75.0
    assert diagnosis["next_action"] == "PREPARE_UNPROVEN_TERMINATION_PENALTY_CLAIM"


def test_e05_supplier_loss_calculation_goes_to_human_review_not_fake_cap(client):
    cid = build_e05_case(
        client, fixed=True, renewed=False, penalty=75.0,
        loss_proof="provided_needs_validation",
    )
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["scope_status"] == "CALCULATION_REVIEW"
    assert body["claimable_amount"] is None
    assert body["next_action"] == "HUMAN_REVIEW_PENALTY_CAP"
    reviews = client.get(f"/api/cases/{cid}/reviews").json()
    assert reviews[0]["status"] == "OPEN"


def test_e05_pre_effective_date_uses_legacy_review(client):
    cid = build_e05_case(client, termination="2026-06-11", penalty=50.0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"
