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


def test_classifier_routes_c02_failed_repair(client):
    response = client.post(
        "/api/cases",
        json={"message": "Compré un portátil, ya lo repararon y volvió a fallar"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vertical"] == "purchases"
    assert body["family"] == "C02"
    assert body["title"] == "Reparación fallida, repetida o demorada"


def test_classifier_routes_c03_wrong_product(client):
    response = client.post(
        "/api/cases",
        json={"message": "Compré un móvil y me enviaron otro modelo distinto a lo anunciado"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vertical"] == "purchases"
    assert body["family"] == "C03"


def build_c02_termination_case(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un portátil, ya lo repararon y volvió a fallar"},
    )
    assert created.status_code == 200
    cid = created.json()["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Portátil",
        "purchase.delivery_date": "2026-01-10",
        "purchase.price": 899.0,
        "purchase.conformity_attempts": 1,
        "purchase.lack_after_conformity_attempt": True,
        "purchase.seller_declared_will_not_conform": False,
        "purchase.defect_description": "Tras la reparación vuelve a apagarse solo",
        "purchase.same_origin_after_repair": True,
        "purchase.repair_return_date": "2026-08-20",
        "purchase.preferred_secondary_remedy": "termination",
        "purchase.defect_material": True,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_c02_failed_repair_can_support_termination_and_refund(client):
    cid = build_c02_termination_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 899.0
    assert body["next_action"] == "PREPARE_C02_TERMINATION"
    assert any(item.get("basis") == "TRLGDCU_122_3" for item in body["burden_of_proof"])

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "C02_TERMINATION_AFTER_FAILED_CONFORMITY"
    assert payload["amount"] == 899.0
    assert "119 ter" in payload["text"]


def test_c02_pending_repair_does_not_invent_fixed_day_deadline(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré una lavadora y sigue en reparación"},
    ).json()
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Lavadora",
        "purchase.delivery_date": "2026-02-10",
        "purchase.price": 520.0,
        "purchase.conformity_attempts": 1,
        "purchase.lack_after_conformity_attempt": False,
        "purchase.repair_still_pending": True,
        "purchase.repair_started_date": "2026-09-01",
        "purchase.seller_declared_will_not_conform": False,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_REPAIR_DELAY"
    assert "no establece un número universal de días" in body["reasoning_summary"]
    reviews = client.get(f"/api/cases/{cid}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "OPEN"


def test_c02_price_reduction_is_not_fabricated_as_cash_amount(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor, tras la reparación sigue fallando"},
    ).json()
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Televisor",
        "purchase.delivery_date": "2026-03-01",
        "purchase.price": 1000.0,
        "purchase.conformity_attempts": 1,
        "purchase.lack_after_conformity_attempt": True,
        "purchase.seller_declared_will_not_conform": False,
        "purchase.defect_description": "Sigue perdiendo imagen",
        "purchase.same_origin_after_repair": False,
        "purchase.preferred_secondary_remedy": "price_reduction",
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose").json()
    assert diagnosis["next_action"] == "PREPARE_C02_PRICE_REDUCTION"
    assert diagnosis["claimable_amount"] == 0.0
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200
    assert claim.json()["amount"] == 0.0
    assert "no se inventa automáticamente" in claim.json()["text"]


def build_c03_case(client, denied=False):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un móvil y me enviaron otro modelo distinto a lo anunciado"},
    )
    assert created.status_code == 200
    cid = created.json()["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Móvil",
        "purchase.delivery_date": "2026-09-01",
        "purchase.price": 699.0,
        "purchase.contract_description": "Modelo X Pro, 256 GB, color negro",
        "purchase.received_description": "Modelo X básico, 128 GB, color negro",
        "purchase.mismatch_confirmed": True,
        "purchase.mismatch_material": True,
        "purchase.seller_denied_conformity": denied,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_c03_wrong_product_builds_conformity_action(client):
    cid = build_c03_case(client, denied=False)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 0.0
    assert body["next_action"] == "PREPARE_C03_CONFORMITY_CLAIM"
    assert "REPLACEMENT_OR_COMPLETION" in body["remedies"]

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "C03_CONTRACT_MISMATCH_CONFORMITY"
    assert payload["amount"] == 0.0
    assert "115 bis" in payload["text"]


def test_c03_seller_refusal_opens_secondary_remedies(client):
    cid = build_c03_case(client, denied=True)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["next_action"] == "PREPARE_C03_ESCALATED_REMEDY"
    assert "PRICE_REDUCTION" in body["remedies"]
    assert "TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT" in body["remedies"]


def test_c03_legacy_case_goes_to_human_review(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un móvil y me enviaron otro modelo"},
    ).json()
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Móvil",
        "purchase.delivery_date": "2021-12-20",
        "purchase.price": 500.0,
        "purchase.contract_description": "Modelo A",
        "purchase.received_description": "Modelo B",
        "purchase.mismatch_confirmed": True,
        "purchase.mismatch_material": True,
        "purchase.seller_denied_conformity": False,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"
    reviews = client.get(f"/api/cases/{cid}/reviews").json()
    assert reviews[0]["status"] == "OPEN"


def test_c02_c03_submission_does_not_invent_purchase_response_deadline(client):
    cid = build_c03_case(client, denied=False)
    client.post(f"/api/cases/{cid}/diagnose")
    client.post(f"/api/cases/{cid}/prepare-claim")
    response = client.post(
        f"/api/cases/{cid}/submission",
        json={"submitted_on": "2026-09-15"},
    )
    assert response.status_code == 200
    assert response.json()["deadline"] is None
    assert response.json()["deadline_status"] == "NOT_CONFIGURED"
