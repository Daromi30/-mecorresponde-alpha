from app.engine.c01 import evaluate_c01
from app.engine.common import FactValue


def f(value, confirmed=True):
    return FactValue(value=value, state="confirmed" if confirmed else "asserted", user_confirmed=confirmed)


def base_facts():
    return {
        "purchase.buyer_is_consumer": f(True),
        "purchase.seller_is_business": f(True),
        "purchase.second_hand": f(False),
        "purchase.product_name": f("Televisor"),
        "purchase.delivery_date": f("2026-01-10"),
        "purchase.defect_manifested_date": f("2026-09-01"),
        "purchase.defect_description": f("La pantalla deja de mostrar imagen"),
        "purchase.accidental_damage_or_misuse": f(False),
        "purchase.price": f(1299.0),
    }


def test_c01_current_warranty_preserves_value_without_fake_cash_refund():
    result = evaluate_c01(base_facts())
    assert result.viability == "HIGH"
    assert result.economic_value == 1299.0
    assert result.claimable_amount == 0.0
    assert "REPAIR" in result.remedies
    assert "REPLACEMENT" in result.remedies
    assert any(x["on"] == "seller" for x in result.burden_of_proof)


def test_c01_after_two_year_presumption_is_medium_not_auto_rejected():
    facts = base_facts()
    facts["purchase.delivery_date"] = f("2023-12-01")
    facts["purchase.defect_manifested_date"] = f("2026-01-15")
    result = evaluate_c01(facts)
    assert result.viability == "MEDIUM"
    assert result.rule_result == "APPLIES"
    assert result.economic_value == 1299.0


def test_c01_after_three_year_manifestation_is_low():
    facts = base_facts()
    facts["purchase.delivery_date"] = f("2022-01-01")
    facts["purchase.defect_manifested_date"] = f("2025-02-01")
    result = evaluate_c01(facts)
    assert result.viability == "LOW"
    assert result.claimable_amount == 0.0


def test_c01_accidental_damage_fails_conformity_tree():
    facts = base_facts()
    facts["purchase.accidental_damage_or_misuse"] = f(True)
    result = evaluate_c01(facts)
    assert result.viability == "LOW"
    assert "known_accidental_damage_or_misuse" in result.failed_conditions


def test_c01_legacy_purchase_requires_review():
    facts = base_facts()
    facts["purchase.delivery_date"] = f("2021-12-15")
    facts["purchase.defect_manifested_date"] = f("2021-12-20")
    result = evaluate_c01(facts)
    assert result.scope_status == "LEGACY_REVIEW"
    assert result.viability == "PROFESSIONAL_REVIEW"


def test_c01_second_hand_not_automated_yet():
    facts = base_facts()
    facts["purchase.second_hand"] = f(True)
    result = evaluate_c01(facts)
    assert result.scope_status == "LIMITED_SCOPE"
    assert result.next_action == "HUMAN_REVIEW_SECOND_HAND"


def test_c01_prior_repair_redirects_to_c02():
    facts = base_facts()
    facts["purchase.repair_attempts"] = f(1)
    result = evaluate_c01(facts)
    assert result.viability == "RECLASSIFY"
    assert result.scope_status == "REDIRECT_C02"


def test_c01_seller_refusal_can_open_secondary_remedies():
    facts = base_facts()
    facts["purchase.seller_denied_conformity"] = f(True)
    facts["purchase.defect_severity"] = f("material")
    result = evaluate_c01(facts)
    assert "PRICE_REDUCTION" in result.remedies
    assert "TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT" in result.remedies


def test_c01_impossible_timeline_requires_correction():
    facts = base_facts()
    facts["purchase.delivery_date"] = f("2026-05-01")
    facts["purchase.defect_manifested_date"] = f("2026-04-01")
    result = evaluate_c01(facts)
    assert result.viability == "INSUFFICIENT_INFORMATION"
    assert result.next_action == "CORRECT_TIMELINE"


def test_c01_company_misuse_argument_downgrades_to_medium():
    facts = base_facts()
    facts["company.asserts_misuse"] = f(True, confirmed=False)
    result = evaluate_c01(facts)
    assert result.viability == "MEDIUM"
    assert any(c["type"] == "ACCIDENTAL_DAMAGE_OR_MISUSE" and c["status"] == "open" for c in result.counterarguments)
