from app.engine.common import FactValue
from app.engine.b02 import evaluate_b02


def fv(v): return FactValue(value=v, state="confirmed", user_confirmed=True)

def base_facts():
    return {
        "bank.user_scope": fv("consumer"), "bank.payer_provider_in_spain": fv(True),
        "bank.operation_authorized": fv(True), "bank.authorized_payment_type": fv("direct_debit"),
        "bank.direct_debit_article_48_2_confirmed": fv(True), "bank.debit_date": fv("2026-08-01"),
        "bank.refund_request_date": fv("2026-09-21"), "bank.article_48_4_exception_status": fv("clearly_absent"),
        "bank.payment_scope_clear": fv(True), "bank.documented_operation_amount": fv(120.0), "bank.refund_received": fv(False),
    }

def test_b02_authorized_direct_debit_within_eight_weeks():
    r=evaluate_b02(base_facts())
    assert r.viability == "HIGH"
    assert r.claimable_amount == 120.0
    assert r.next_action == "PREPARE_B02_AUTHORIZED_DIRECT_DEBIT_REFUND"

def test_b02_includes_eight_week_boundary():
    f=base_facts(); f["bank.debit_date"]=fv("2026-07-27"); f["bank.refund_request_date"]=fv("2026-09-21")
    assert evaluate_b02(f).viability == "HIGH"

def test_b02_after_eight_weeks_fails_closed():
    f=base_facts(); f["bank.debit_date"]=fv("2026-07-26")
    assert evaluate_b02(f).next_action == "HUMAN_REVIEW_B02_OUTSIDE_EIGHT_WEEKS"

def test_b02_article_48_4_possible_fails_closed():
    f=base_facts(); f["bank.article_48_4_exception_status"]=fv("possible_or_unknown")
    assert evaluate_b02(f).next_action == "HUMAN_REVIEW_B02_ARTICLE_48_4"

def test_b02_unauthorized_redirects_b01():
    f=base_facts(); f["bank.operation_authorized"]=fv(False)
    assert evaluate_b02(f).next_action == "RECLASSIFY_B01_UNAUTHORIZED_PAYMENT"
