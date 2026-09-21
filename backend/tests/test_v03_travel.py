from app.engine.common import FactValue
from app.engine.v01 import CURRENT_RULE_REVIEW_BEFORE
from app.engine.v03 import evaluate_v03


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "travel.denied_boarding_involuntary": fv(True),
        "travel.departure_airport_in_eu": fv(True),
        "travel.confirmed_reservation": fv(True),
        "travel.presentation_requirement_met": fv(True),
        "travel.fare_status": fv("public_fare"),
        "travel.denied_boarding_reason": fv("operational_or_no_reason"),
        "travel.distance_band": fv("le_1500"),
        "travel.rerouted_to_final_destination": fv(False),
        "travel.compensation_received": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_v03_calculates_full_short_distance_compensation():
    result = evaluate_v03(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 250.0
    assert result.economic_value == 250.0
    assert result.next_action == "PREPARE_V03_DENIED_BOARDING_COMPENSATION"
    assert result.calculation["article_7_2_reduction_applied"] is False


def test_v03_applies_article_7_2_reduction_when_rerouting_arrives_within_threshold():
    facts = base_facts()
    facts["travel.distance_band"] = fv("other_gt_3500")
    facts["travel.rerouted_to_final_destination"] = fv(True)
    facts["travel.rerouting_arrival_delay_hours"] = fv(3.5)

    result = evaluate_v03(facts)

    assert result.viability == "HIGH"
    assert result.claimable_amount == 300.0
    assert result.calculation["base_compensation"] == 600.0
    assert result.calculation["article_7_2_reduction_applied"] is True


def test_v03_keeps_full_compensation_when_rerouting_exceeds_threshold():
    facts = base_facts()
    facts["travel.distance_band"] = fv("other_1500_3500")
    facts["travel.rerouted_to_final_destination"] = fv(True)
    facts["travel.rerouting_arrival_delay_hours"] = fv(3.5)

    result = evaluate_v03(facts)

    assert result.claimable_amount == 400.0
    assert result.calculation["article_7_2_reduction_applied"] is False


def test_v03_excludes_reasonable_article_2j_ground():
    facts = base_facts()
    facts["travel.denied_boarding_reason"] = fv("inadequate_travel_documents")

    result = evaluate_v03(facts)

    assert result.viability == "LOW"
    assert result.rule_result == "FAILED"
    assert result.next_action == "EXPLAIN_V03_REASONABLE_GROUND_EXCLUSION"


def test_v03_unclear_reason_fails_closed():
    facts = base_facts()
    facts["travel.denied_boarding_reason"] = fv("unclear")

    result = evaluate_v03(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V03_DENIAL_REASON"


def test_v03_requires_valid_presentation():
    facts = base_facts()
    facts["travel.presentation_requirement_met"] = fv(False)

    result = evaluate_v03(facts)

    assert result.viability == "OUT_OF_SCOPE"
    assert result.next_action == "EXPLAIN_V03_PRESENTATION_SCOPE_NOT_MET"


def test_v03_rule_has_preemptive_reform_guard():
    facts = base_facts()
    facts["system.analysis_date"] = fv(CURRENT_RULE_REVIEW_BEFORE.isoformat())

    result = evaluate_v03(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V03_LEGAL_TRANSITION"


def test_v03_api_prepares_compensation_with_eurlex_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Por overbooking no me dejaron embarcar en mi vuelo"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "V03"
    assert case["vertical"] == "travel"

    for key, fact in base_facts().items():
        if key == "system.analysis_date":
            continue
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
    assert body["claim_type"] == "V03_INVOLUNTARY_DENIED_BOARDING_COMPENSATION"
    assert body["amount"] == 250.0
    assert body["legal_basis"][0]["rule_id"] == "AIR_INVOLUNTARY_DENIED_BOARDING_COMPENSATION_CURRENT"
    assert body["legal_basis"][0]["article"] == "2(j), 3.2, 4.3, 7"
    assert body["legal_basis"][0]["official_url"].startswith("https://eur-lex.europa.eu/")
