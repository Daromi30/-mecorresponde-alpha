from app.engine.common import FactValue
from app.engine.s01 import evaluate_s01


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "insurance.claimant_role": fv("insured"),
        "insurance.counterparty_type": fv("insurer"),
        "insurance.claim_declaration_received_by_insurer": fv(True),
        "insurance.claim_declaration_received_date": fv("2026-07-01"),
        "insurance.claim_declaration_receipt_evidence": fv(True),
        "insurance.insurer_acknowledged_minimum_amount": fv(True),
        "insurance.acknowledged_minimum_amount": fv(1250.0),
        "insurance.minimum_payment_received": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_s01_requests_only_acknowledged_outstanding_minimum_after_forty_days():
    result = evaluate_s01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 1250.0
    assert result.next_action == "PREPARE_S01_INSURANCE_MINIMUM_PAYMENT"
    assert result.calculation["forty_days_elapsed"] is True
    assert result.calculation["article_20_default_interest_calculated"] is False


def test_s01_waits_before_forty_day_boundary():
    facts = base_facts()
    facts["insurance.claim_declaration_received_date"] = fv("2026-09-01")
    facts["system.analysis_date"] = fv("2026-09-21")

    result = evaluate_s01(facts)

    assert result.viability == "LOW"
    assert result.next_action == "WAIT_S01_ARTICLE_18_FORTY_DAYS"
    assert result.calculation["forty_days_elapsed"] is False


def test_s01_does_not_decide_unacknowledged_minimum_or_coverage():
    facts = base_facts()
    facts["insurance.insurer_acknowledged_minimum_amount"] = fv(False)

    result = evaluate_s01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_S01_MINIMUM_AMOUNT_NOT_ACKNOWLEDGED"


def test_s01_requires_evidence_of_claim_receipt_date():
    facts = base_facts()
    facts["insurance.claim_declaration_receipt_evidence"] = fv(False)

    result = evaluate_s01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_S01_RECEIPT_EVIDENCE"


def test_s01_subtracts_verified_partial_payment():
    facts = base_facts()
    facts["insurance.minimum_payment_received"] = fv(True)
    facts["insurance.minimum_payment_received_amount"] = fv(250.0)

    result = evaluate_s01(facts)

    assert result.viability == "HIGH"
    assert result.claimable_amount == 1000.0


def test_s01_api_prepares_minimum_payment_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi aseguradora ha reconocido una cantidad mínima por el siniestro pero no me la paga"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "S01"
    assert case["vertical"] == "insurance"

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
    assert body["claim_type"] == "S01_ACKNOWLEDGED_INSURANCE_MINIMUM_PAYMENT"
    assert body["amount"] == 1250.0
    assert body["legal_basis"][0]["rule_id"] == "INSURANCE_MINIMUM_PAYMENT_CURRENT"
    assert body["legal_basis"][0]["article"] == "18"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "no cuantifica intereses de mora" in body["text"]
