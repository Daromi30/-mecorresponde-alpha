from app.engine.common import FactValue
from app.engine.t01 import evaluate_t01


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "telecom.subscriber_has_contract": fv(True),
        "telecom.service_kind": fv("fixed_internet"),
        "telecom.service_restored": fv(True),
        "telecom.interruption_duration_hours": fv(12.0),
        "telecom.affected_hours_8_22": fv(8.0),
        "telecom.interruption_due_to_serious_subscriber_breach": fv(False),
        "telecom.interruption_due_to_nonconforming_terminal_damage": fv(False),
        "telecom.internet_fee_identified": fv(True),
        "telecom.monthly_internet_fixed_fee": fv(40.0),
        "telecom.billing_period_days": fv(30),
        "telecom.compensation_already_applied": fv(False),
    }


def test_t01_calculates_prorated_fixed_internet_compensation():
    result = evaluate_t01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 0.67
    assert result.economic_value == 0.67
    assert result.next_action == "PREPARE_T01_INTERNET_INTERRUPTION_COMPENSATION"
    assert result.calculation["automatic_credit_threshold_met"] is True


def test_t01_uses_statutory_half_of_bundle_when_services_are_not_sold_separately():
    facts = base_facts()
    facts["telecom.internet_fee_identified"] = fv(False)
    facts.pop("telecom.monthly_internet_fixed_fee")
    facts["telecom.bundle_total_monthly_price"] = fv(60.0)
    facts["telecom.operator_sells_services_separately"] = fv(False)

    result = evaluate_t01(facts)

    assert result.viability == "HIGH"
    assert result.calculation["monthly_internet_fixed_fee"] == 30.0
    assert result.calculation["fee_basis"] == "statutory_50_percent_bundle"
    assert result.claimable_amount == 0.5


def test_t01_fails_closed_for_mobile_attribution():
    facts = base_facts()
    facts["telecom.service_kind"] = fv("mobile_internet")

    result = evaluate_t01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.scope_status == "LIMITED_SCOPE"
    assert result.next_action == "HUMAN_REVIEW_MOBILE_INTERRUPTION"


def test_t01_respects_article_16_2_exclusions():
    facts = base_facts()
    facts["telecom.interruption_due_to_serious_subscriber_breach"] = fv(True)

    result = evaluate_t01(facts)

    assert result.viability == "LOW"
    assert result.claimable_amount == 0.0
    assert result.rule_result == "FAILED"


def test_t01_api_prepares_claim_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi fibra estuvo sin internet 12 horas y no me han compensado"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "T01"
    assert case["vertical"] == "telecom"

    for key, fact in base_facts().items():
        response = client.post(
            f"/api/cases/{case['id']}/facts",
            json={
                "key": key,
                "value": fact.value,
                "state": "confirmed",
                "user_confirmed": True,
            },
        )
        assert response.status_code == 200, response.text

    diagnosis = client.post(f"/api/cases/{case['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH"

    prepared = client.post(f"/api/cases/{case['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["claim_type"] == "T01_FIXED_INTERNET_INTERRUPTION_COMPENSATION"
    assert body["amount"] == 0.67
    assert body["legal_basis"][0]["rule_id"] == "TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION"
    assert body["legal_basis"][0]["article"] == "16"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
