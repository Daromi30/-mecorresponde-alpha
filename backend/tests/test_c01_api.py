def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(f"/api/cases/{cid}/facts", json={
        "key": key, "value": value, "state": state, "user_confirmed": user_confirmed,
    })
    assert response.status_code == 200
    return response.json()


def build_c01_case(client):
    created = client.post("/api/cases", json={
        "message": "Compré un televisor en una tienda, está defectuoso y me rechazan la garantía"
    })
    assert created.status_code == 200
    body = created.json()
    assert body["vertical"] == "purchases"
    assert body["family"] == "C01"
    cid = body["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.second_hand": False,
        "purchase.product_name": "Televisor",
        "purchase.delivery_date": "2026-01-10",
        "purchase.defect_manifested_date": "2026-09-01",
        "purchase.defect_description": "La pantalla se queda negra",
        "purchase.accidental_damage_or_misuse": False,
        "purchase.price": 1299.0,
        "purchase.seller_denied_conformity": True,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_c01_end_to_end_diagnosis(client):
    cid = build_c01_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["economic_value"] == 1299.0
    assert body["claimable_amount"] == 0.0
    assert "REPAIR" in body["remedies"]
    assert "PRICE_REDUCTION" in body["remedies"]


def test_c01_can_prepare_action_even_when_cash_claim_is_zero(client):
    cid = build_c01_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200
    body = claim.json()
    assert body["claim_type"] == "GOODS_CONFORMITY"
    assert body["amount"] == 0.0
    assert body["economic_value"] == 1299.0
    assert "117 a 121" in body["text"]


def test_c01_submission_does_not_invent_electricity_deadline(client):
    cid = build_c01_case(client)
    client.post(f"/api/cases/{cid}/diagnose")
    client.post(f"/api/cases/{cid}/prepare-claim")
    response = client.post(f"/api/cases/{cid}/submission", json={"submitted_on": "2026-09-15"})
    assert response.status_code == 200
    body = response.json()
    assert body["deadline"] is None
    assert body["deadline_status"] == "NOT_CONFIGURED"


def test_c01_company_misuse_response_reanalyzes_case(client):
    cid = build_c01_case(client)
    first = client.post(f"/api/cases/{cid}/diagnose").json()
    assert first["viability"] == "HIGH"
    response = client.post(f"/api/cases/{cid}/responses", json={
        "text": "Rechazamos la garantía porque el equipo presenta daño por golpe y mal uso."
    })
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["type"] == "DENIAL"
    assert body["updated_diagnosis"]["viability"] == "MEDIUM"


def test_c01_legacy_case_is_queued_for_human_review(client):
    created = client.post("/api/cases", json={
        "message": "Compré un televisor en una tienda y está defectuoso"
    }).json()
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.second_hand": False,
        "purchase.product_name": "Televisor",
        "purchase.delivery_date": "2021-12-15",
        "purchase.defect_manifested_date": "2021-12-20",
        "purchase.defect_description": "No enciende",
        "purchase.accidental_damage_or_misuse": False,
        "purchase.price": 799.0,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"
    reviews = client.get(f"/api/cases/{cid}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "OPEN"
