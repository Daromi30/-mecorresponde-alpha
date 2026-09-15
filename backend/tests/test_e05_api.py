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


def create_e05(client, message="Me cobran una penalización por cambiar de compañía de luz"):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertical"] == "electricity"
    assert body["family"] == "E05"
    return body["id"]


def fill_scope(client, cid, termination_date="2026-09-01", penalty=85.0):
    for key, value in {
        "electricity.consumer_natural_person": True,
        "electricity.segment_2_0td": True,
        "electricity.termination_date": termination_date,
        "electricity.termination_penalty_amount": penalty,
    }.items():
        post_fact(client, cid, key, value)


def test_e05_classifier_and_clear_no_penalty_refund(client):
    cid = create_e05(client)
    fill_scope(client, cid)
    post_fact(client, cid, "electricity.switch_to_pvpc_as_vulnerable", False)
    post_fact(client, cid, "electricity.fixed_price_contract", False)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 85.0
    assert body["next_action"] == "PREPARE_E05_PENALTY_REFUND"

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "E05_TERMINATION_PENALTY_REFUND"
    assert payload["amount"] == 85.0
    assert "28.3" in payload["text"]


def test_e05_fixed_price_before_first_renewal_requires_human_review(client):
    cid = create_e05(client)
    fill_scope(client, cid, penalty=120.0)
    for key, value in {
        "electricity.switch_to_pvpc_as_vulnerable": False,
        "electricity.fixed_price_contract": True,
        "electricity.before_first_annual_renewal": True,
        "electricity.supplier_provided_direct_loss_proof": False,
        "electricity.supplier_provided_penalty_calculation": True,
    }.items():
        post_fact(client, cid, key, value)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_FIXED_PRICE_PENALTY"
    assert body["claimable_amount"] is None
    assert any(item.get("basis") == "RD88_2026_28_3" for item in body["burden_of_proof"])

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 422
    reviews = client.get(f"/api/cases/{cid}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "OPEN"


def test_e05_fixed_price_after_first_renewal_is_no_penalty_case(client):
    cid = create_e05(client, "Me aplican una permanencia en mi contrato de luz al cambiarme")
    fill_scope(client, cid, penalty=64.5)
    for key, value in {
        "electricity.switch_to_pvpc_as_vulnerable": False,
        "electricity.fixed_price_contract": True,
        "electricity.before_first_annual_renewal": False,
    }.items():
        post_fact(client, cid, key, value)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 64.5


def test_e05_vulnerable_pvpc_does_not_require_fixed_price_fact(client):
    cid = create_e05(client)
    fill_scope(client, cid, penalty=40.0)
    post_fact(client, cid, "electricity.switch_to_pvpc_as_vulnerable", True)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 40.0
    assert body["missing_facts"] == []
    assert "28.9" in body["reasoning_summary"]


def test_e05_day_before_current_rule_is_legacy_review(client):
    cid = create_e05(client)
    fill_scope(client, cid, termination_date="2026-06-11", penalty=90.0)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["scope_status"] == "LEGACY_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_LEGACY"


def test_e05_company_fixed_price_argument_reanalyzes_and_reduces_confidence(client):
    cid = create_e05(client)
    fill_scope(client, cid, penalty=75.0)
    post_fact(client, cid, "electricity.switch_to_pvpc_as_vulnerable", False)
    post_fact(client, cid, "electricity.fixed_price_contract", False)
    first = client.post(f"/api/cases/{cid}/diagnose").json()
    assert first["viability"] == "HIGH"

    response = client.post(
        f"/api/cases/{cid}/responses",
        json={"text": "La penalización es válida porque era un contrato a precio fijo y se canceló durante el primer año, antes de la primera prórroga anual."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["type"] == "DENIAL"
    assert body["updated_diagnosis"] is not None
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"


def test_c03_company_match_argument_now_triggers_reanalysis(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un móvil y me enviaron otro modelo distinto a lo anunciado"},
    ).json()
    cid = created["id"]
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Móvil",
        "purchase.delivery_date": "2026-09-01",
        "purchase.price": 699.0,
        "purchase.contract_description": "Modelo X Pro, 256 GB",
        "purchase.received_description": "Modelo X básico, 128 GB",
        "purchase.mismatch_confirmed": True,
        "purchase.mismatch_material": True,
        "purchase.seller_denied_conformity": False,
    }.items():
        post_fact(client, cid, key, value)
    first = client.post(f"/api/cases/{cid}/diagnose").json()
    assert first["viability"] == "HIGH"

    response = client.post(
        f"/api/cases/{cid}/responses",
        json={"text": "Rechazamos su reclamación: el producto entregado coincide con lo pedido y corresponde con lo comprado."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["updated_diagnosis"] is not None
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"
