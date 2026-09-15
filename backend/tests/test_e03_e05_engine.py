from app.engine.common import FactValue
from app.engine.e03 import evaluate_e03
from app.engine.e05 import evaluate_e05


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def test_e03_golden_no_consent_current_regime():
    result = evaluate_e03({
        "electricity.switch_effective_date": fv("2026-02-12"),
        "electricity.previous_supplier": fv("Anterior"),
        "electricity.incoming_supplier": fv("Nueva"),
        "electricity.possible_identity_theft": fv(False),
        "electricity.switch_cups_correct": fv(True),
        "electricity.express_consent_given": fv(False),
        "electricity.consent_evidence_status": fv("not_provided"),
        "electricity.unsolicited_supply_amount_paid": fv(0.0),
    })
    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.next_action == "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION"


def test_e03_golden_valid_consent_correct_cups_fails_branch():
    result = evaluate_e03({
        "electricity.switch_effective_date": fv("2026-09-01"),
        "electricity.previous_supplier": fv("Anterior"),
        "electricity.incoming_supplier": fv("Nueva"),
        "electricity.possible_identity_theft": fv(False),
        "electricity.switch_cups_correct": fv(True),
        "electricity.express_consent_given": fv(True),
        "electricity.consent_evidence_status": fv("valid_durable_proof"),
        "electricity.unsolicited_supply_amount_paid": fv(0.0),
    })
    assert result.viability == "LOW"
    assert result.rule_result == "FAILED"


def test_e03_golden_identity_theft_never_auto_resolves():
    result = evaluate_e03({
        "electricity.switch_effective_date": fv("2026-09-01"),
        "electricity.previous_supplier": fv("Anterior"),
        "electricity.incoming_supplier": fv("Nueva"),
        "electricity.possible_identity_theft": fv(True),
    })
    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_IDENTITY_THEFT"


def test_e05_golden_effective_date_boundary():
    before = evaluate_e05({"electricity.termination_date": fv("2026-06-11")})
    assert before.scope_status == "LEGACY_REVIEW"

    current = evaluate_e05({
        "electricity.termination_date": fv("2026-06-12"),
        "electricity.contract_holder_is_natural_person": fv(True),
        "electricity.tariff_is_2_0td": fv(True),
        "electricity.termination_penalty_charged": fv(40.0),
        "electricity.contract_is_fixed_price": fv(False),
        "electricity.first_annual_renewal_already_occurred": fv(False),
    })
    assert current.viability == "HIGH"
    assert current.claimable_amount == 40.0


def test_e05_golden_fixed_price_exception_needs_supplier_proof():
    result = evaluate_e05({
        "electricity.termination_date": fv("2026-09-01"),
        "electricity.contract_holder_is_natural_person": fv(True),
        "electricity.tariff_is_2_0td": fv(True),
        "electricity.termination_penalty_charged": fv(100.0),
        "electricity.contract_is_fixed_price": fv(True),
        "electricity.first_annual_renewal_already_occurred": fv(False),
    })
    assert result.viability == "MEDIUM"
    assert result.claimable_amount is None
    assert result.next_action == "REQUEST_PENALTY_JUSTIFICATION"


def test_e05_golden_supplier_calculation_is_not_auto_validated():
    result = evaluate_e05({
        "electricity.termination_date": fv("2026-09-01"),
        "electricity.contract_holder_is_natural_person": fv(True),
        "electricity.tariff_is_2_0td": fv(True),
        "electricity.termination_penalty_charged": fv(100.0),
        "electricity.contract_is_fixed_price": fv(True),
        "electricity.first_annual_renewal_already_occurred": fv(False),
        "electricity.supplier_direct_loss_proof_status": fv("provided_needs_validation"),
    })
    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.claimable_amount is None
    assert result.next_action == "HUMAN_REVIEW_PENALTY_CAP"
