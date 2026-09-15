def post_fact(client, cid, key, value):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_current_decision_exposes_exact_official_legal_sources(client):
    created = client.post(
        "/api/cases",
        json={"message": "La compañía de luz me aplica un precio distinto al contratado"},
    )
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    facts = {
        "electricity.consumer_natural_person": True,
        "electricity.market_type": "free_market",
        "electricity.pricing_issue_date": "2026-09-01",
        "electricity.pricing_issue_type": "contracted_price_mismatch",
        "electricity.pricing_contract_or_offer_evidence_available": True,
        "electricity.pricing_promised_terms": "0,12 €/kWh",
        "electricity.pricing_applied_terms": "0,18 €/kWh",
        "electricity.pricing_difference_confirmed": True,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text

    response = client.get(f"/api/cases/{cid}/legal-sources")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_id"] == diagnosis.json()["decision_id"]
    assert {item["rule_id"] for item in body["sources"]} == {
        "ELEC_PRICING_TERMS_CURRENT",
        "CONSUMER_OFFER_BINDING",
    }
    for item in body["sources"]:
        assert item["rule_version_id"]
        assert item["version"] >= 1
        assert item["article"]
        assert item["authority"]
        assert item["title"]
        assert item["official_url"].startswith("https://")
        assert item["jurisdiction"] == "ES"
        assert item["review_status"] == "approved"


def test_sources_are_empty_before_diagnosis(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor defectuoso y me rechazan la garantía"},
    )
    cid = created.json()["id"]
    response = client.get(f"/api/cases/{cid}/legal-sources")
    assert response.status_code == 200
    assert response.json() == {"decision_id": None, "sources": []}
