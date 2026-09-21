from app.engine.common import FactValue
from app.engine.t02 import evaluate_t02


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "telecom.final_user_contract": fv(True),
        "telecom.change_notice_received": fv(True),
        "telecom.change_exception_type": fv("adverse_or_other"),
        "telecom.change_notice_date": fv("2026-09-10"),
        "telecom.change_effective_date": fv("2026-10-15"),
        "telecom.notice_informed_free_termination_right": fv(True),
        "telecom.notice_clear_and_durable": fv(True),
        "telecom.contract_contains_valid_change_reason": fv(True),
        "telecom.user_wants_to_terminate": fv(True),
        "telecom.retains_subsidized_terminal": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_t02_supports_free_termination_with_verified_current_notice():
    result = evaluate_t02(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 0.0
    assert result.next_action == "PREPARE_T02_FREE_TERMINATION_NOTICE"
    assert result.calculation["exercise_until"] == "2026-10-10"
    assert result.calculation["lead_time_compliant"] is True
    assert result.remedies == ["TERMINATE_WITHOUT_ADDITIONAL_COST"]


def test_t02_missing_scope_fact_does_not_emit_legal_conclusion():
    facts = base_facts()
    facts.pop("telecom.final_user_contract")

    result = evaluate_t02(facts)

    assert result.viability == "INSUFFICIENT_INFORMATION"
    assert result.rule_result == "PENDING"
    assert "telecom.final_user_contract" in result.missing_facts


def test_t02_excluded_change_does_not_create_free_termination_right():
    facts = base_facts()
    facts["telecom.change_exception_type"] = fv("legally_required")

    result = evaluate_t02(facts)

    assert result.viability == "LOW"
    assert result.rule_result == "FAILED"
    assert result.next_action == "EXPLAIN_T02_EXCLUDED_CHANGE"


def test_t02_unknown_exception_fails_closed():
    facts = base_facts()
    facts["telecom.change_exception_type"] = fv("unknown")

    result = evaluate_t02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_T02_CHANGE_EXCEPTION"


def test_t02_defective_notice_does_not_invent_legal_consequence():
    facts = base_facts()
    facts["telecom.notice_informed_free_termination_right"] = fv(False)

    result = evaluate_t02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_T02_DEFECTIVE_NOTICE_OR_REASON"


def test_t02_subsidized_terminal_requires_review_before_promising_zero_cost():
    facts = base_facts()
    facts["telecom.retains_subsidized_terminal"] = fv(True)

    result = evaluate_t02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_T02_SUBSIDIZED_TERMINAL"


def test_t02_user_can_decline_to_exercise_the_option_without_other_remedy_being_invented():
    facts = base_facts()
    facts["telecom.user_wants_to_terminate"] = fv(False)
    facts.pop("telecom.retains_subsidized_terminal")

    result = evaluate_t02(facts)

    assert result.viability == "LOW"
    assert result.rule_result == "APPLIES"
    assert result.next_action == "EXPLAIN_T02_FREE_TERMINATION_OPTION"


def test_t02_api_prepares_notice_with_exact_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi operadora de fibra me ha subido el precio y cambia las condiciones"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "T02"
    assert case["vertical"] == "telecom"

    for key, fact in base_facts().items():
        if key == "system.analysis_date":
            continue
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
    assert body["claim_type"] == "T02_FREE_TERMINATION_AFTER_CONTRACT_CHANGE"
    assert body["amount"] == 0.0
    assert body["legal_basis"][0]["rule_id"] == "TELECOM_CONTRACT_CHANGE_FREE_TERMINATION"
    assert body["legal_basis"][0]["article"] == "67.8 y 67.10"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "mantener indefinidamente" in body["text"]
