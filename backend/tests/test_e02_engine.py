from app.engine.common import FactValue
from app.engine.e02 import evaluate_e02a, evaluate_e02b


def F(v, state="confirmed", confirmed=True):
    return FactValue(v, state, confirmed)


def test_e02a_overbilling_current_rule():
    f = {
        "electricity.billing.invoice_date": F("2026-07-01"),
        "electricity.billing.billed_amount": F(120.0),
        "electricity.billing.correct_amount": F(80.0),
    }
    r = evaluate_e02a(f)
    assert r.viability == "HIGH"
    assert r.claimable_amount == 40.0


def test_e02a_legacy_before_effective_date():
    f = {
        "electricity.billing.invoice_date": F("2026-05-30"),
        "electricity.billing.billed_amount": F(120.0),
        "electricity.billing.correct_amount": F(80.0),
    }
    r = evaluate_e02a(f)
    assert r.scope_status == "LEGACY_REVIEW"


def test_e02a_no_overbilling():
    f = {
        "electricity.billing.invoice_date": F("2026-07-01"),
        "electricity.billing.billed_amount": F(80.0),
        "electricity.billing.correct_amount": F(80.0),
    }
    r = evaluate_e02a(f)
    assert r.viability == "LOW"
    assert r.claimable_amount == 0


def test_e02b_duplicate_charge():
    f = {
        "electricity.billing.same_debt": F(True),
        "electricity.billing.duplicate_charges": F([
            {"amount": 74.30, "evidence_verified": True},
            {"amount": 74.30, "evidence_verified": True},
        ]),
    }
    r = evaluate_e02b(f)
    assert r.viability == "HIGH"
    assert r.claimable_amount == 74.30


def test_e02b_similar_charges_not_enough_without_same_debt():
    f = {
        "electricity.billing.duplicate_charges": F([
            {"amount": 74.30, "evidence_verified": True},
            {"amount": 74.30, "evidence_verified": True},
        ]),
    }
    r = evaluate_e02b(f)
    assert r.viability == "INSUFFICIENT_INFORMATION"


def test_e02b_different_debts_no_duplicate():
    f = {
        "electricity.billing.same_debt": F(False),
        "electricity.billing.duplicate_charges": F([
            {"amount": 74.30, "evidence_verified": True},
            {"amount": 74.30, "evidence_verified": True},
        ]),
    }
    r = evaluate_e02b(f)
    assert r.viability == "LOW"
