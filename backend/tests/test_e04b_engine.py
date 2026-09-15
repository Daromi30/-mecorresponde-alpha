from app.engine.e04b import FactValue, evaluate_e04b


def F(v, state="confirmed", confirmed=True): return FactValue(v,state,confirmed)

def base():
    return {
      "electricity.supply_end_date":F("2026-06-03"),
      "electricity.addon.identity":F("Protección Hogar"),
      "electricity.addon.ever_contracted":F(True),
      "electricity.addon.contracted_with_supply":F(True),
      "electricity.addon.keep_requested":F(False),
      "electricity.addon.charges":F([
        {"amount":8.99,"service_period_start":"2026-06-04","service_period_end":"2026-07-03","evidence_verified":True},
        {"amount":8.99,"service_period_start":"2026-07-04","service_period_end":"2026-08-03","evidence_verified":True},
        {"amount":8.99,"service_period_start":"2026-08-04","service_period_end":"2026-09-03","evidence_verified":True},
      ])
    }

def test_g01_high_2697():
    r=evaluate_e04b(base()); assert r.viability=="HIGH"; assert r.claimable_amount==26.97; assert r.next_action=="PREPARE_INITIAL_CLAIM"

def test_g02_keep_requested_low():
    f=base(); f["electricity.addon.keep_requested"]=F(True); r=evaluate_e04b(f); assert r.viability=="LOW"; assert r.claimable_amount==0

def test_g03_independent_contract_low():
    f=base(); f["electricity.addon.contracted_with_supply"]=F(False); r=evaluate_e04b(f); assert r.viability=="LOW"

def test_g04_never_contracted_reclassifies():
    f=base(); f["electricity.addon.ever_contracted"]=F(False); r=evaluate_e04b(f); assert r.scope_status=="REDIRECT_E04A"

def test_g05_post_charge_date_but_pre_period_not_claimed():
    f=base(); f["electricity.addon.charges"]=F([{
      "amount":8.99,"service_period_start":"2026-05-01","service_period_end":"2026-06-03","charged_at":"2026-06-10","evidence_verified":True
    }]); r=evaluate_e04b(f); assert r.claimable_amount==0

def test_g06_unknown_period_insufficient():
    f=base(); f["electricity.addon.charges"]=F([{"amount":8.99,"charged_at":"2026-06-15","evidence_verified":True}]); r=evaluate_e04b(f); assert r.viability=="INSUFFICIENT_INFORMATION"

def test_g07_missing_end_date():
    f=base(); del f["electricity.supply_end_date"]; r=evaluate_e04b(f); assert "electricity.supply_end_date" in r.missing_facts

def test_g09_joint_unknown():
    f=base(); del f["electricity.addon.contracted_with_supply"]; r=evaluate_e04b(f); assert r.viability=="INSUFFICIENT_INFORMATION"

def test_g14_partial_refund_remaining_one_charge():
    f=base(); f["electricity.addon.charges"]=F([{
      "amount":8.99,"service_period_start":"2026-08-04","service_period_end":"2026-09-03","evidence_verified":True
    }]); r=evaluate_e04b(f); assert r.claimable_amount==8.99

def test_g16_legacy():
    f=base(); f["electricity.supply_end_date"]=F("2026-01-31"); r=evaluate_e04b(f); assert r.scope_status=="LEGACY_REVIEW"

def test_g17_boundary_supported():
    f=base(); f["electricity.supply_end_date"]=F("2026-02-12"); r=evaluate_e04b(f); assert r.scope_status=="SUPPORTED"

def test_g20_zero_charge_no_claim():
    f=base(); f["electricity.addon.charges"]=F([{
      "amount":0,"service_period_start":"2026-06-04","service_period_end":"2026-07-03","evidence_verified":True
    }]); r=evaluate_e04b(f); assert r.claimable_amount==0

def test_mixed_period_not_prorated():
    f=base(); f["electricity.addon.charges"]=F([{
      "amount":10,"service_period_start":"2026-05-20","service_period_end":"2026-06-19","evidence_verified":True
    }]); r=evaluate_e04b(f); assert r.claimable_amount==0; assert any(c["type"]=="MIXED_SERVICE_PERIOD" for c in r.counterarguments)

def test_unverified_charge_not_counted():
    f=base(); f["electricity.addon.charges"]=F([{
      "amount":50,"service_period_start":"2026-06-04","service_period_end":"2026-07-03","evidence_verified":False
    }]); r=evaluate_e04b(f); assert r.claimable_amount==0
