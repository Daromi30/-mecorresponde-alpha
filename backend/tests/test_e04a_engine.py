from app.engine.common import FactValue
from app.engine.e04a import evaluate_e04a


def F(v, state="confirmed", confirmed=True):
    return FactValue(v, state, confirmed)


def base():
    return {
        "electricity.addon.identity": F("Protección Hogar"),
        "electricity.addon.ever_contracted": F(False),
        "electricity.addon.charges": F([
            {"amount": 8.99, "evidence_verified": True},
            {"amount": 8.99, "evidence_verified": True},
        ]),
    }


def test_e04a_high_when_never_contracted_and_charges_verified():
    r = evaluate_e04a(base())
    assert r.viability == "HIGH"
    assert r.claimable_amount == 17.98


def test_e04a_reclassifies_when_user_recognizes_contract():
    f = base(); f["electricity.addon.ever_contracted"] = F(True)
    r = evaluate_e04a(f)
    assert r.viability == "RECLASSIFY"


def test_e04a_verified_consent_kills_basis():
    f = base(); f["electricity.addon.consent_proven"] = F(True)
    r = evaluate_e04a(f)
    assert r.viability == "LOW"
    assert r.claimable_amount == 0


def test_e04a_company_consent_assertion_lowers_to_medium():
    f = base(); f["company.asserts_consent"] = F(True, state="asserted", confirmed=False)
    r = evaluate_e04a(f)
    assert r.viability == "MEDIUM"
    assert any(c["type"] == "CONSENT_EVIDENCE" for c in r.counterarguments)
