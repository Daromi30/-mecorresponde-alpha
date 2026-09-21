from app.engine.common import FactValue
from app.engine.s02 import evaluate_s02


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "insurance.contract_role": fv("policyholder"),
        "insurance.policy_kind": fv("non_life"),
        "insurance.automatic_renewal_provided": fv(True),
        "insurance.policyholder_wants_nonrenewal": fv(True),
        "insurance.current_period_end_date": fv("2026-12-31"),
        "insurance.current_period_end_date_evidence": fv(True),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_s02_prepares_nonrenewal_when_at_least_one_calendar_month_remains():
    result = evaluate_s02(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.next_action == "PREPARE_S02_POLICY_NONRENEWAL_NOTICE"
    assert result.claimable_amount == 0.0
    assert result.calculation["last_safe_notice_date"] == "2026-11-30"


def test_s02_includes_exact_last_safe_calendar_date():
    facts = base_facts()
    facts["insurance.current_period_end_date"] = fv("2026-10-31")
    facts["system.analysis_date"] = fv("2026-09-30")

    result = evaluate_s02(facts)

    assert result.viability == "HIGH"
    assert result.next_action == "PREPARE_S02_POLICY_NONRENEWAL_NOTICE"


def test_s02_late_notice_fails_closed():
    facts = base_facts()
    facts["insurance.current_period_end_date"] = fv("2026-10-15")
    facts["system.analysis_date"] = fv("2026-09-21")

    result = evaluate_s02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_S02_LATE_NONRENEWAL"


def test_s02_life_insurance_is_not_automated():
    facts = base_facts()
    facts["insurance.policy_kind"] = fv("life")

    result = evaluate_s02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_S02_LIFE_INSURANCE"


def test_s02_requires_evidence_of_period_end():
    facts = base_facts()
    facts["insurance.current_period_end_date_evidence"] = fv(False)

    result = evaluate_s02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_S02_PERIOD_END_EVIDENCE"


def test_s02_api_prepares_written_nonrenewal_notice_with_official_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "No quiero que se renueve automáticamente mi seguro cuando venza"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "S02"
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
    assert body["claim_type"] == "S02_POLICYHOLDER_NONRENEWAL_NOTICE"
    assert body["amount"] == 0.0
    assert body["legal_basis"][0]["rule_id"] == "INSURANCE_POLICYHOLDER_NON_RENEWAL_CURRENT"
    assert body["legal_basis"][0]["article"] == "22.2 y 22.5"
    assert body["legal_basis"][0]["official_url"].startswith("https://www.boe.es/")
    assert "no pretende resolver anticipadamente" in body["text"]
