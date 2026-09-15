from app.engine.c04 import evaluate_c04
from app.engine.common import FactValue


def fv(value, confirmed=True):
    return FactValue(value=value, state="confirmed" if confirmed else "asserted", user_confirmed=confirmed)


def base(**overrides):
    values = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": "2026-07-01",
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
        "system.analysis_date": "2026-09-15",
    }
    values.update(overrides)
    return {key: fv(value) for key, value in values.items()}


def test_c04_overdue_requires_additional_period_before_refund():
    result = evaluate_c04(base())
    assert result.viability == "HIGH"
    assert result.claimable_amount == 0.0
    assert result.economic_value == 149.90
    assert result.next_action == "ASK_IF_ADDITIONAL_PERIOD_GIVEN"
    assert "purchase.additional_delivery_period_requested" in result.missing_facts


def test_c04_overdue_without_additional_period_prepares_delivery_demand():
    result = evaluate_c04(base(purchase__unused=None, **{"purchase.additional_delivery_period_requested": False}))
    assert result.viability == "HIGH"
    assert result.claimable_amount == 0.0
    assert result.next_action == "GIVE_ADDITIONAL_DELIVERY_PERIOD"
    assert result.remedies == ["DELIVERY"]


def test_c04_additional_period_still_running_waits():
    result = evaluate_c04(base(**{
        "purchase.additional_delivery_period_requested": True,
        "purchase.additional_delivery_period_deadline": "2026-09-20",
    }))
    assert result.next_action == "WAIT_ADDITIONAL_DELIVERY_PERIOD"
    assert result.claimable_amount == 0.0


def test_c04_additional_period_expired_allows_termination_and_refund():
    result = evaluate_c04(base(**{
        "purchase.additional_delivery_period_requested": True,
        "purchase.additional_delivery_period_deadline": "2026-09-10",
    }))
    assert result.viability == "HIGH"
    assert result.next_action == "PREPARE_NON_DELIVERY_TERMINATION"
    assert result.claimable_amount == 149.90
    assert "TERMINATE_CONTRACT" in result.remedies
    assert result.calculation["termination_reason"] == "additional_period_expired"


def test_c04_clear_seller_refusal_allows_immediate_termination():
    result = evaluate_c04(base(**{"purchase.seller_refused_delivery": True}))
    assert result.next_action == "PREPARE_NON_DELIVERY_TERMINATION"
    assert result.claimable_amount == 149.90
    assert result.calculation["termination_reason"] == "seller_refused_delivery"


def test_c04_essential_agreed_date_breach_allows_immediate_termination():
    result = evaluate_c04(base(**{
        "purchase.delivery_date_was_agreed": True,
        "purchase.agreed_delivery_date": "2026-08-01",
        "purchase.delivery_date_essential": True,
    }))
    assert result.next_action == "PREPARE_NON_DELIVERY_TERMINATION"
    assert result.calculation["termination_reason"] == "essential_delivery_date_breached"


def test_c04_before_delivery_due_does_not_invent_refund_right():
    result = evaluate_c04(base(**{
        "purchase.order_date": "2026-09-01",
        "system.analysis_date": "2026-09-15",
    }))
    assert result.rule_result == "NOT_YET_DUE"
    assert result.claimable_amount == 0.0
    assert result.next_action == "WAIT_UNTIL_DELIVERY_DUE"


def test_c04_delivered_order_is_reclassified():
    result = evaluate_c04(base(**{"purchase.delivered": True}))
    assert result.scope_status == "REDIRECT_OTHER_PURCHASE_ISSUE"
    assert result.next_action == "RECLASSIFY_DELIVERED_ORDER"


def test_c04_business_buyer_is_out_of_scope():
    result = evaluate_c04(base(**{"purchase.buyer_is_consumer": False}))
    assert result.viability == "OUT_OF_SCOPE"
    assert result.rule_result == "NOT_APPLICABLE"


def test_c04_legacy_order_requires_human_review():
    result = evaluate_c04(base(**{"purchase.order_date": "2021-12-01"}))
    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.scope_status == "LEGACY_REVIEW"


def test_c04_seller_delivery_assertion_reduces_viability():
    result = evaluate_c04(base(**{
        "purchase.seller_refused_delivery": True,
        "company.asserts_delivered": True,
    }))
    assert result.viability == "MEDIUM"
    assert any(c["type"] == "SELLER_ASSERTS_DELIVERY" for c in result.counterarguments)


def test_c04_burden_records_seller_delivery_proof():
    result = evaluate_c04(base())
    assert any(item["on"] == "seller" and item["basis"] == "TRLGDCU_66_BIS_5" for item in result.burden_of_proof)
