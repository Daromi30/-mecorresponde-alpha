from app.engine.c05 import evaluate_c05
from app.engine.common import FactValue


def fv(value, confirmed=True):
    return FactValue(value=value, state="confirmed" if confirmed else "asserted", user_confirmed=confirmed)


def base(**overrides):
    values = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": "2026-09-05",
        "purchase.amount_paid": 120.0,
        "purchase.premium_delivery_extra": 0.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": False,
        "system.analysis_date": "2026-09-15",
    }
    values.update(overrides)
    return {key: fv(value) for key, value in values.items()}


def test_c05_right_still_available_prepares_withdrawal_notice():
    result = evaluate_c05(base())
    assert result.viability == "HIGH"
    assert result.next_action == "SEND_WITHDRAWAL_NOTICE"
    assert result.claimable_amount == 0.0
    assert result.calculation["deadline"] == "2026-09-19"


def test_c05_late_withdrawal_after_informed_deadline_is_low():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-09-20",
    }))
    assert result.viability == "LOW"
    assert result.next_action == "EXPLAIN_LATE_WITHDRAWAL"
    assert "withdrawal_sent_after_deadline" in result.failed_conditions


def test_c05_missing_information_extends_deadline():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_information_provided": False,
        "purchase.withdrawal_information_later_date": None,
        "purchase.withdrawal_sent": False,
        "system.analysis_date": "2027-01-10",
    }))
    assert result.viability == "HIGH"
    assert result.next_action == "SEND_WITHDRAWAL_NOTICE"
    assert result.calculation["basis"] == "missing_information_12_month_extension"
    assert result.calculation["deadline"] == "2027-09-19"


def test_c05_late_information_starts_new_14_day_window():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_information_provided": False,
        "purchase.withdrawal_information_later_date": "2026-10-01",
        "purchase.withdrawal_sent": False,
        "system.analysis_date": "2026-10-05",
    }))
    assert result.next_action == "SEND_WITHDRAWAL_NOTICE"
    assert result.calculation["basis"] == "late_information_plus_14_days"
    assert result.calculation["deadline"] == "2026-10-15"


def test_c05_possible_article_103_exception_forces_human_review():
    result = evaluate_c05(base(**{"purchase.withdrawal_exception_possible": True}))
    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.scope_status == "LIMITED_SCOPE"
    assert result.next_action == "HUMAN_REVIEW_WITHDRAWAL_EXCEPTION"


def test_c05_valid_withdrawal_requires_return_before_cash_enforcement_when_no_collection():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-09-10",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": False,
        "purchase.return_sent": False,
    }))
    assert result.viability == "HIGH"
    assert result.next_action == "RETURN_GOODS_WITH_PROOF"
    assert result.claimable_amount == 0.0
    assert any(c["type"] == "SELLER_MAY_WITHHOLD_PENDING_RETURN" for c in result.counterarguments)


def test_c05_valid_withdrawal_refund_period_running_waits():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-09-10",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": False,
        "purchase.return_sent": True,
        "purchase.return_proof_available": True,
        "system.analysis_date": "2026-09-15",
    }))
    assert result.next_action == "WAIT_WITHDRAWAL_REFUND_PERIOD"
    assert result.claimable_amount == 120.0
    assert result.calculation["refund_due_date"] == "2026-09-24"


def test_c05_overdue_refund_becomes_claimable():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-08-20",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": False,
        "purchase.return_sent": True,
        "purchase.return_proof_available": True,
        "system.analysis_date": "2026-09-15",
    }))
    assert result.viability == "HIGH"
    assert result.next_action == "PREPARE_WITHDRAWAL_REFUND_CLAIM"
    assert result.claimable_amount == 120.0


def test_c05_premium_delivery_extra_is_not_added_to_refund():
    result = evaluate_c05(base(**{
        "purchase.amount_paid": 130.0,
        "purchase.premium_delivery_extra": 10.0,
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-08-20",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": True,
        "system.analysis_date": "2026-09-15",
    }))
    assert result.claimable_amount == 120.0
    assert result.calculation["refundable_amount"] == 120.0


def test_c05_full_refund_closes_money_issue():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-09-10",
        "purchase.refund_received": True,
        "purchase.refund_received_amount": 120.0,
    }))
    assert result.claimable_amount == 0.0
    assert result.next_action == "VERIFY_AND_CLOSE_WITHDRAWAL"
    assert result.rule_result == "SATISFIED"


def test_c05_company_exception_assertion_reduces_viability():
    result = evaluate_c05(base(**{
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-08-20",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": True,
        "company.asserts_withdrawal_exception": True,
        "system.analysis_date": "2026-09-15",
    }))
    assert result.viability == "MEDIUM"
    assert any(c["type"] == "SELLER_ASSERTS_WITHDRAWAL_EXCEPTION" for c in result.counterarguments)


def test_c05_legacy_receipt_requires_human_review():
    result = evaluate_c05(base(**{"purchase.received_date": "2022-05-20"}))
    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.scope_status == "LEGACY_REVIEW"


def test_c05_non_distance_purchase_is_out_of_scope_for_this_family():
    result = evaluate_c05(base(**{"purchase.distance_contract": False}))
    assert result.viability == "OUT_OF_SCOPE"
    assert result.next_action == "RECLASSIFY_NON_DISTANCE_PURCHASE"


def test_c05_consumer_bears_proof_of_exercising_withdrawal():
    result = evaluate_c05(base())
    assert any(item["on"] == "consumer" and item["basis"] == "TRLGDCU_106_4" for item in result.burden_of_proof)
