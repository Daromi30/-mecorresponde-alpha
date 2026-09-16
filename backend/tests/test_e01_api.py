def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={"key": key, "value": value, "state": state, "user_confirmed": user_confirmed},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_e01(client, message="En mi factura de luz me aplican un precio distinto al contratado"):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertical"] == "electricity"
    assert body["family"] == "E01"
    assert body["title"] == "Precio, tarifa o descuento eléctrico distinto de lo contratado"
    return body["id"]


def fill_base(client, cid, *, issue_type, issue_date="2026-09-01", consumer=True, market="free_market", evidence=True):
    facts = {
        "electricity.consumer_natural_person": consumer,
        "electricity.market_type": market,
        "electricity.pricing_issue_date": issue_date,
        "electricity.pricing_issue_type": issue_type,
        "electricity.pricing_contract_or_offer_evidence_available": evidence,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)


def test_e01_contract_price_mismatch_builds_non_fabricated_correction(client):
    cid = create_e01(client)
    fill_base(client, cid, issue_type="contracted_price_mismatch")
    post_fact(client, cid, "electricity.pricing_promised_terms", "0,12 €/kWh")
    post_fact(client, cid, "electricity.pricing_applied_terms", "0,18 €/kWh")
    post_fact(client, cid, "electricity.pricing_difference_confirmed", True)
    post_fact(client, cid, "electricity.pricing_estimated_affected_amount", 86.0)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 0.0
    assert body["economic_value"] == 86.0
    assert body["next_action"] == "PREPARE_E01_PRICING_CORRECTION"

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "E01_CONTRACTED_PRICE_OR_TARIFF_CORRECTION"
    assert payload["amount"] == 0.0
    assert payload["amount_status"] == "REQUIRES_VERIFIED_BILLING_CALCULATION"
    assert "artículo 61" in payload["text"]


def test_e01_tariff_mismatch_is_supported(client):
    cid = create_e01(client, "Mi tarifa de luz es distinta a la que contraté")
    fill_base(client, cid, issue_type="tariff_mismatch")
    post_fact(client, cid, "electricity.pricing_promised_terms", "Tarifa fija 24h")
    post_fact(client, cid, "electricity.pricing_applied_terms", "Tarifa con tres periodos")
    post_fact(client, cid, "electricity.pricing_difference_confirmed", True)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E01_PRICING_CORRECTION"


def test_e01_discount_promised_but_not_applied(client):
    cid = create_e01(client, "En la luz no me aplican el descuento que me prometieron")
    fill_base(client, cid, issue_type="discount_mismatch")
    post_fact(client, cid, "electricity.discount_duration_and_terms_disclosed", True)
    post_fact(client, cid, "electricity.discount_application_matches_promised_terms", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E01_DISCOUNT_CORRECTION"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "E01_PROMOTIONAL_DISCOUNT_CORRECTION"


def test_e01_discount_terms_not_disclosed_is_transparency_issue_not_fake_refund(client):
    cid = create_e01(client, "Mi compañía eléctrica me quitó un descuento promocional y no decía cuánto duraba")
    fill_base(client, cid, issue_type="discount_mismatch")
    post_fact(client, cid, "electricity.discount_duration_and_terms_disclosed", False)
    post_fact(client, cid, "electricity.discount_application_matches_promised_terms", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 0.0
    assert "30.1.k" in body["reasoning_summary"]


def test_e01_discount_applied_as_disclosed_is_low(client):
    cid = create_e01(client, "Creo que no me respetan el descuento de mi tarifa eléctrica")
    fill_base(client, cid, issue_type="discount_mismatch")
    post_fact(client, cid, "electricity.discount_duration_and_terms_disclosed", True)
    post_fact(client, cid, "electricity.discount_application_matches_promised_terms", True)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_DISCOUNT_APPLIED_AS_AGREED"


def test_e01_without_contract_or_offer_evidence_requests_evidence(client):
    cid = create_e01(client)
    fill_base(client, cid, issue_type="contracted_price_mismatch", evidence=False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "INSUFFICIENT_INFORMATION"
    assert body["next_action"] == "REQUEST_CONTRACT_OR_OFFER_EVIDENCE"


def test_e01_pvpc_and_business_cases_are_not_auto_decided(client):
    pvpc = create_e01(client, "En mi factura de luz regulada me aplican una tarifa distinta")
    fill_base(client, pvpc, issue_type="tariff_mismatch", market="pvpc")
    body = client.post(f"/api/cases/{pvpc}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["scope_status"] == "PVPC_REVIEW"

    business = create_e01(client, "En la tarifa eléctrica de mi negocio me cobran otro precio distinto al contratado")
    fill_base(client, business, issue_type="contracted_price_mismatch", consumer=False)
    body = client.post(f"/api/cases/{business}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_BUSINESS_PRICING"


def test_e01_legacy_case_uses_historical_review(client):
    cid = create_e01(client)
    fill_base(client, cid, issue_type="contracted_price_mismatch", issue_date="2026-06-11")
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["scope_status"] == "LEGACY_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_LEGACY"


def test_e01_company_says_pricing_matches_contract_reduces_confidence(client):
    cid = create_e01(client)
    fill_base(client, cid, issue_type="contracted_price_mismatch")
    post_fact(client, cid, "electricity.pricing_promised_terms", "0,12 €/kWh")
    post_fact(client, cid, "electricity.pricing_applied_terms", "0,18 €/kWh")
    post_fact(client, cid, "electricity.pricing_difference_confirmed", True)
    assert client.post(f"/api/cases/{cid}/diagnose").json()["viability"] == "HIGH"
    assert client.post(f"/api/cases/{cid}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{cid}/submission",
        json={"submitted_on": "2026-09-15", "channel": "web"},
    )
    assert submitted.status_code == 200, submitted.text

    response = client.post(
        f"/api/cases/{cid}/responses/evidenced",
        json={
            "text": "El precio coincide con el contrato firmado y por tanto rechazamos su reclamación.",
            "received_on": "2026-09-16",
            "channel": "email",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["type"] == "DENIAL"
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"
    assert any(
        item["type"] == "SUPPLIER_ASSERTS_PRICING_MATCHES_CONTRACT"
        for item in body["updated_diagnosis"]["counterarguments"]
    )


def test_e01_and_e07_are_classified_as_different_problems(client):
    e01 = client.post(
        "/api/cases",
        json={"message": "La compañía de luz me aplica un precio distinto al contratado"},
    ).json()
    assert e01["family"] == "E01"

    e07 = client.post(
        "/api/cases",
        json={"message": "Mi compañía de luz me ha subido el precio sin avisar"},
    ).json()
    assert e07["family"] == "E07"
