from app.engine.b01 import evaluate_b01
from app.engine.common import FactValue


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "bank.user_scope": fv("consumer"),
        "bank.payer_provider_in_spain": fv(True),
        "bank.operation_unauthorized": fv(True),
        "bank.debit_date": fv("2026-09-18"),
        "bank.awareness_date": fv("2026-09-18"),
        "bank.notification_date": fv("2026-09-18"),
        "bank.provider_supplied_operation_info": fv(True),
        "bank.payment_initiation_provider_involved": fv(False),
        "bank.instrument_status": fv("not_lost_stolen_or_misappropriated"),
        "bank.provider_alleges_fraud_or_gross_negligence": fv(False),
        "bank.provider_fraud_suspicion_status": fv("none"),
        "bank.documented_operation_amount": fv(175.0),
        "bank.refund_received": fv(False),
    }


def test_b01_requests_documented_unauthorized_payment_refund_in_narrow_safe_scope():
    result = evaluate_b01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 175.0
    assert result.next_action == "PREPARE_B01_UNAUTHORIZED_PAYMENT_REFUND"
    assert result.calculation["article_46_loss_allocation_automated"] is False
    assert "PROVIDER_MUST_PROVE_AUTHENTICATION_AND_CORRECT_RECORDING" in result.burden_of_proof


def test_b01_does_not_turn_article_43_undue_delay_into_an_invented_day_limit():
    facts = base_facts()
    facts["bank.awareness_date"] = fv("2026-09-18")
    facts["bank.notification_date"] = fv("2026-09-22")

    result = evaluate_b01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_B01_NOTIFICATION_PROMPTNESS"


def test_b01_outside_thirteen_months_with_missing_provider_information_fails_closed():
    facts = base_facts()
    facts["bank.debit_date"] = fv("2025-01-01")
    facts["bank.awareness_date"] = fv("2026-03-01")
    facts["bank.notification_date"] = fv("2026-03-01")
    facts["bank.provider_supplied_operation_info"] = fv(False)

    result = evaluate_b01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_B01_13_MONTH_INFORMATION_EXCEPTION"


def test_b01_lost_or_stolen_instrument_never_assumes_exact_fifty_euro_loss():
    facts = base_facts()
    facts["bank.instrument_status"] = fv("lost_stolen_or_misappropriated")

    result = evaluate_b01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.claimable_amount is None
    assert result.next_action == "HUMAN_REVIEW_B01_ARTICLE_46_INSTRUMENT"


def test_b01_fraud_or_gross_negligence_allegation_requires_evidence_review():
    facts = base_facts()
    facts["bank.provider_alleges_fraud_or_gross_negligence"] = fv(True)

    result = evaluate_b01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_B01_FRAUD_OR_GROSS_NEGLIGENCE"
    assert "PROVIDER_MUST_PROVE_FRAUD_OR_GROSS_NEGLIGENCE" in result.burden_of_proof


def test_b01_provider_fraud_suspicion_reported_to_bde_requires_review():
    facts = base_facts()
    facts["bank.provider_fraud_suspicion_status"] = fv("reported_to_bde")

    result = evaluate_b01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_B01_PROVIDER_FRAUD_SUSPICION"


def test_b01_api_prepares_refund_with_boe_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi banco me ha cargado un pago que no reconozco y no he autorizado"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "B01"
    assert case["vertical"] == "banking"

    for key, fact in base_facts().items():
        response = client.post(
            f"/api/cases/{case['id']}/facts",
            json={"key": key, "value": fact.value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200, response.text

    diagnosis = client.post(f"/api/cases/{case['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 175.0

    prepared = client.post(f"/api/cases/{case['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    package = prepared.json()
    assert package["claim_type"] == "B01_UNAUTHORIZED_PAYMENT_REFUND"
    assert package["amount"] == 175.0
    assert package["legal_basis"][0]["rule_id"] == "PAYMENT_UNAUTHORIZED_REFUND_CURRENT"
    assert package["legal_basis"][0]["article"] == "34, 43, 44, 45 y 46"
    assert package["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "mero registro" in package["text"]
