from app.engine.common import FactValue
from app.engine.a01 import evaluate_a01


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "automotive.workshop_in_spain": fv(True),
        "automotive.vehicle_type": fv("non_industrial"),
        "automotive.repair_delivery_date": fv("2026-08-01"),
        "automotive.repair_documentation_available": fv(True),
        "automotive.failure_date": fv("2026-09-01"),
        "automotive.km_since_repair": fv(500),
        "automotive.failure_repaired_part_status": fv("same_repaired_part"),
        "automotive.third_party_manipulation_after_repair": fv(False),
        "automotive.refused_hidden_anomaly_causal_status": fv("no"),
    }


def test_a01_supports_free_repair_for_same_part_within_time_and_km():
    result = evaluate_a01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 0.0
    assert result.next_action == "PREPARE_A01_FREE_REPAIR_NOTICE"
    assert result.calculation["within_three_months"] is True
    assert result.calculation["within_2000_km"] is True


def test_a01_includes_time_and_km_boundary():
    facts = base_facts()
    facts["automotive.repair_delivery_date"] = fv("2026-06-30")
    facts["automotive.failure_date"] = fv("2026-09-30")
    facts["automotive.km_since_repair"] = fv(2000)

    result = evaluate_a01(facts)

    assert result.viability == "HIGH"


def test_a01_outside_minimum_window_does_not_prepare_guarantee_claim():
    time_facts = base_facts()
    time_facts["automotive.repair_delivery_date"] = fv("2026-05-01")
    assert evaluate_a01(time_facts).next_action == "EXPLAIN_A01_MINIMUM_GUARANTEE_EXPIRED"

    km_facts = base_facts()
    km_facts["automotive.km_since_repair"] = fv(2001)
    assert evaluate_a01(km_facts).next_action == "EXPLAIN_A01_MINIMUM_GUARANTEE_EXPIRED"


def test_a01_unclear_repaired_part_or_third_party_fails_closed():
    unclear = base_facts()
    unclear["automotive.failure_repaired_part_status"] = fv("unclear")
    assert evaluate_a01(unclear).next_action == "HUMAN_REVIEW_A01_REPAIRED_PART_CAUSATION"

    third_party = base_facts()
    third_party["company.asserts_automotive_third_party_manipulation"] = fv(True)
    assert evaluate_a01(third_party).next_action == "HUMAN_REVIEW_A01_THIRD_PARTY_MANIPULATION"


def test_a01_industrial_vehicle_uses_separate_review_scope():
    facts = base_facts()
    facts["automotive.vehicle_type"] = fv("industrial")

    result = evaluate_a01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_A01_VEHICLE_TYPE"


def test_a01_api_prepares_free_repair_notice_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "El taller reparó mi coche y volvió a fallar"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "A01"
    assert case["vertical"] == "automotive"

    for key, fact in base_facts().items():
        response = client.post(
            f"/api/cases/{case['id']}/facts",
            json={"key": key, "value": fact.value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200, response.text

    diagnosis = client.post(f"/api/cases/{case['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH"

    prepared = client.post(f"/api/cases/{case['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["claim_type"] == "A01_WORKSHOP_FREE_REPAIR_GUARANTEE"
    assert body["amount"] == 0.0
    assert body["legal_basis"][0]["rule_id"] == "AUTOMOTIVE_REPAIR_GUARANTEE_CURRENT"
    assert body["legal_basis"][0]["article"] == "16.1-16.6"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "reparación gratuita" in body["text"]
