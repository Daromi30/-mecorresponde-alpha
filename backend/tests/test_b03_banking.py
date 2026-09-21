from app.engine.common import FactValue
from app.engine.b03 import evaluate_b03


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "bank.customer_is_consumer": fv(True),
        "bank.entity_is_credit_institution": fv(True),
        "bank.commission_service_scope": fv("ordinary_banking_service"),
        "bank.commission_charge_date": fv("2026-09-15"),
        "bank.commission_amount": fv(60.0),
        "bank.commission_request_acceptance_status": fv("not_requested_or_accepted"),
        "bank.commission_service_performance_status": fv("provided_or_expense_incurred"),
        "bank.commission_refund_received": fv(False),
    }


def test_b03_missing_request_or_acceptance_supports_refund():
    result = evaluate_b03(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 60.0
    assert result.next_action == "PREPARE_B03_BANK_FEE_REFUND"


def test_b03_service_not_provided_supports_refund_even_if_accepted():
    facts = base_facts()
    facts["bank.commission_request_acceptance_status"] = fv("accepted")
    facts["bank.commission_service_performance_status"] = fv("not_provided_or_no_expense")

    result = evaluate_b03(facts)

    assert result.viability == "HIGH"
    assert result.claimable_amount == 60.0


def test_b03_does_not_call_a_documented_provided_fee_invalid():
    facts = base_facts()
    facts["bank.commission_request_acceptance_status"] = fv("accepted")
    facts["bank.commission_service_performance_status"] = fv("provided_or_expense_incurred")

    result = evaluate_b03(facts)

    assert result.viability == "LOW"
    assert result.claimable_amount == 0.0
    assert result.next_action == "EXPLAIN_B03_CHARGING_CONDITIONS_MET"


def test_b03_evidence_gap_fails_closed():
    facts = base_facts()
    facts["bank.commission_request_acceptance_status"] = fv("unknown")

    result = evaluate_b03(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_B03_EVIDENCE_GAP"


def test_b03_non_consumer_or_sectoral_service_fails_closed():
    business = base_facts()
    business["bank.customer_is_consumer"] = fv(False)
    assert evaluate_b03(business).next_action == "HUMAN_REVIEW_B03_NON_CONSUMER_SCOPE"

    investment = base_facts()
    investment["bank.commission_service_scope"] = fv("investment")
    assert evaluate_b03(investment).next_action == "HUMAN_REVIEW_B03_SERVICE_SCOPE"


def test_b03_api_prepares_refund_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi banco me ha cobrado una comisión por un servicio que no solicité"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "B03"
    assert case["vertical"] == "banking"

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
    assert body["claim_type"] == "B03_UNREQUESTED_OR_UNPROVIDED_BANK_FEE_REFUND"
    assert body["amount"] == 60.0
    assert body["legal_basis"][0]["rule_id"] == "BANK_FEE_REQUEST_AND_SERVICE_CURRENT"
    assert body["legal_basis"][0]["article"] == "2 y 3.1"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "no sostiene que la cuantía" in body["text"]
