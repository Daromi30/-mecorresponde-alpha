def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={"key": key, "value": value, "state": state, "user_confirmed": user_confirmed},
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


def test_e05_clear_no_penalty_refund(client):
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
    assert claim.json()["amount"] == 85.0
    assert "28.3" in claim.json()["text"]


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
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_FIXED_PRICE_PENALTY"
    assert body["claimable_amount"] is None
    assert any(item.get("basis") == "RD88_2026_28_3" for item in body["burden_of_proof"])
    blocked = client.post(f"/api/cases/{cid}/prepare-claim")
    assert blocked.status_code == 409
    assert "does not permit preparing" in blocked.json()["detail"].lower()
    assert client.get(f"/api/cases/{cid}/reviews").json()[0]["status"] == "OPEN"


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
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 40.0
    assert body["missing_facts"] == []
    assert "28.9" in body["reasoning_summary"]


def test_e05_out_of_scope_non_person_20td_is_manual(client):
    cid = create_e05(client)
    for key, value in {
        "electricity.consumer_natural_person": False,
        "electricity.segment_2_0td": True,
        "electricity.termination_date": "2026-09-01",
        "electricity.termination_penalty_amount": 90.0,
    }.items():
        post_fact(client, cid, key, value)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "OUT_OF_SCOPE"
    assert body["scope_status"] == "LIMITED_SCOPE"
    assert body["next_action"] == "HUMAN_REVIEW_CONTRACTUAL_PENALTY"


def test_e05_legacy_before_current_rule_effective(client):
    cid = create_e05(client)
    fill_scope(client, cid, termination_date="2026-05-01", penalty=35.0)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["scope_status"] == "LEGACY_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_LEGACY"
