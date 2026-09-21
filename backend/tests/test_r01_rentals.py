from app.engine.common import FactValue
from app.engine.r01 import evaluate_r01


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "rental.contract_type": fv("dwelling"),
        "rental.lease_ended": fv(True),
        "rental.keys_delivered_date": fv("2026-08-01"),
        "rental.keys_delivery_proof_available": fv(True),
        "rental.deposit_type": fv("statutory_cash_deposit"),
        "rental.refundable_balance_status": fv("confirmed_amount"),
        "rental.confirmed_refundable_balance": fv(900.0),
        "rental.refund_received": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_r01_claims_only_confirmed_outstanding_deposit_balance():
    result = evaluate_r01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 900.0
    assert result.next_action == "PREPARE_R01_RENTAL_DEPOSIT_RETURN"
    assert result.calculation["legal_interest_accrues"] is True
    assert result.calculation["legal_interest_amount_calculated"] is False


def test_r01_uses_calendar_month_for_interest_trigger():
    before = base_facts()
    before["rental.keys_delivered_date"] = fv("2026-08-31")
    before["system.analysis_date"] = fv("2026-09-29")
    assert evaluate_r01(before).calculation["legal_interest_accrues"] is False

    on_boundary = base_facts()
    on_boundary["rental.keys_delivered_date"] = fv("2026-08-31")
    on_boundary["system.analysis_date"] = fv("2026-09-30")
    assert evaluate_r01(on_boundary).calculation["legal_interest_accrues"] is True


def test_r01_does_not_decide_disputed_deductions():
    facts = base_facts()
    facts["rental.refundable_balance_status"] = fv("deductions_or_amount_disputed")

    result = evaluate_r01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_R01_REFUNDABLE_BALANCE"


def test_r01_does_not_treat_additional_guarantee_as_statutory_deposit():
    facts = base_facts()
    facts["rental.deposit_type"] = fv("additional_guarantee")

    result = evaluate_r01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_R01_DEPOSIT_TYPE"


def test_r01_requires_evidence_of_keys_date_before_interest_conclusion():
    facts = base_facts()
    facts["rental.keys_delivery_proof_available"] = fv(False)

    result = evaluate_r01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_R01_KEYS_DATE_EVIDENCE"


def test_r01_api_prepares_principal_only_claim_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi casero no me devuelve la fianza del alquiler después de entregar las llaves"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "R01"
    assert case["vertical"] == "rentals"

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
    assert body["claim_type"] == "R01_CONFIRMED_RENTAL_DEPOSIT_RETURN"
    assert body["amount"] == 900.0
    assert body["amount_status"] == "PRINCIPAL_ONLY_LEGAL_INTEREST_NOT_CALCULATED"
    assert body["legal_basis"][0]["rule_id"] == "RENTAL_DEPOSIT_RETURN_CURRENT"
    assert body["legal_basis"][0]["article"] == "36.4"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "no inventa" in body["text"]
