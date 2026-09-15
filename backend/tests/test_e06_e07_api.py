def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={"key": key, "value": value, "state": state, "user_confirmed": user_confirmed},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_case(client, message, family):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vertical"] == "electricity"
    assert body["family"] == family
    return body["id"]


def fill_e06_base(client, cid, issue_type, invoice_date="2026-09-01", technical=False):
    for key, value in {
        "electricity.reading_issue_invoice_date": invoice_date,
        "electricity.meter_fraud_tampering_or_complex_technical_issue": technical,
        "electricity.reading_issue_type": issue_type,
    }.items():
        post_fact(client, cid, key, value)


def test_e06_remote_reading_failure_without_bimonthly_real_reading(client):
    cid = create_case(client, "Mi factura de luz tiene una lectura estimada porque falló la lectura remota", "E06")
    fill_e06_base(client, cid, "estimated_reading")
    post_fact(client, cid, "electricity.estimated_reading_reason", "remote_reading_failure")
    post_fact(client, cid, "electricity.real_reading_obtained_within_bimonthly_cycle", False)

    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E06_READING_CORRECTION"
    assert "REQUEST_REAL_READING" in body["remedies"]

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "E06_READING_CORRECTION"
    assert claim.json()["amount"] == 0.0


def test_e06_no_access_estimate_without_required_notice(client):
    cid = create_case(client, "Me estimaron el consumo de luz porque dicen que no pudieron acceder al contador", "E06")
    fill_e06_base(client, cid, "estimated_reading")
    post_fact(client, cid, "electricity.estimated_reading_reason", "no_meter_access")
    post_fact(client, cid, "electricity.impossible_reading_notice_received", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E06_READING_CORRECTION"


def test_e06_no_access_notice_and_no_user_reading_can_allow_estimate(client):
    cid = create_case(client, "Tengo consumo estimado de electricidad porque no pudieron leer el contador", "E06")
    fill_e06_base(client, cid, "estimated_reading")
    post_fact(client, cid, "electricity.estimated_reading_reason", "no_meter_access")
    post_fact(client, cid, "electricity.impossible_reading_notice_received", True)
    post_fact(client, cid, "electricity.user_supplied_reading_within_10_business_days", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_ESTIMATION_ALLOWED"


def test_e06_underbilling_regularization_over_one_year_is_challenged_without_invented_amount(client):
    cid = create_case(client, "Me han mandado una regularización de la factura de luz de muchos meses", "E06")
    fill_e06_base(client, cid, "underbilling_regularization")
    post_fact(client, cid, "electricity.regularization_period_months", 18)
    post_fact(client, cid, "electricity.regularization_amount", 420.0)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 0.0
    assert body["economic_value"] == 420.0
    assert body["next_action"] == "PREPARE_E06_LIMIT_REGULARIZATION"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["amount"] == 0.0
    assert claim.json()["amount_status"] == "REQUIRES_MONTHLY_BREAKDOWN"
    assert "máximo de un año" in claim.json()["text"]


def test_e06_regularization_within_one_year_not_automatically_wrong(client):
    cid = create_case(client, "Tengo una regularización de consumo eléctrico por facturación anterior de menos", "E06")
    fill_e06_base(client, cid, "underbilling_regularization")
    post_fact(client, cid, "electricity.regularization_period_months", 8)
    post_fact(client, cid, "electricity.regularization_amount", 180.0)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_REGULARIZATION_PERIOD_WITHIN_LIMIT"


def test_e06_legacy_and_technical_cases_escalate(client):
    legacy = create_case(client, "Factura de luz con lectura estimada", "E06")
    fill_e06_base(client, legacy, "estimated_reading", invoice_date="2026-06-11")
    body = client.post(f"/api/cases/{legacy}/diagnose").json()
    assert body["scope_status"] == "LEGACY_REVIEW"

    technical = create_case(client, "Regularización eléctrica por supuesto contador manipulado", "E06")
    fill_e06_base(client, technical, "underbilling_regularization", technical=True)
    body = client.post(f"/api/cases/{technical}/diagnose").json()
    assert body["viability"] == "PROFESSIONAL_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_METER_TECHNICAL"


def fill_e07_notice(client, cid, *, kind, effective="2026-09-01", received=False, notice_date=None, separate=False):
    post_fact(client, cid, "electricity.contract_change_effective_date", effective)
    post_fact(client, cid, "electricity.contract_change_kind", kind)
    post_fact(client, cid, "electricity.change_notice_received", received)
    if received:
        post_fact(client, cid, "electricity.change_notice_date", notice_date or "2026-07-15")
        post_fact(client, cid, "electricity.change_notice_separate_from_invoice", separate)


def test_e07_unilateral_condition_change_without_notice(client):
    cid = create_case(client, "Mi compañía de luz me ha subido el precio sin avisar", "E07")
    fill_e07_notice(client, cid, kind="contract_condition_change", received=False)
    post_fact(client, cid, "electricity.notice_informed_free_termination_right", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E07_CHANGE_CHALLENGE"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "E07_CONTRACT_CHANGE_NOTICE_CHALLENGE"
    assert claim.json()["amount"] == 0.0


def test_e07_condition_change_with_compliant_notice_not_automatically_invalid(client):
    cid = create_case(client, "Me han cambiado las condiciones de mi contrato de electricidad", "E07")
    fill_e07_notice(
        client,
        cid,
        kind="contract_condition_change",
        received=True,
        notice_date="2026-07-15",
        separate=True,
    )
    post_fact(client, cid, "electricity.notice_informed_free_termination_right", True)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_VALID_NOTICE_AND_EXIT_RIGHT"


def test_e07_contractual_price_review_missing_transitional_content(client):
    cid = create_case(client, "Me aplican una revisión de precio en mi contrato de luz", "E07")
    fill_e07_notice(client, cid, kind="contractual_price_review", received=True, notice_date="2026-07-01", separate=True)
    for key, value in {
        "electricity.fixed_price_contract": False,
        "electricity.price_review_formula_preagreed": True,
        "electricity.price_review_reasons_scope_explained": True,
        "electricity.price_review_transitional_content_complete": False,
    }.items():
        post_fact(client, cid, key, value)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E07_PRICE_REVIEW_CHALLENGE"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "E07_PRICE_REVIEW_NOTICE_CHALLENGE"


def test_e07_proper_contractual_price_review_can_be_procedurally_compliant(client):
    cid = create_case(client, "Revisión de precios de mi tarifa eléctrica", "E07")
    fill_e07_notice(client, cid, kind="contractual_price_review", received=True, notice_date="2026-07-01", separate=True)
    for key, value in {
        "electricity.fixed_price_contract": False,
        "electricity.price_review_formula_preagreed": True,
        "electricity.price_review_reasons_scope_explained": True,
        "electricity.price_review_transitional_content_complete": True,
    }.items():
        post_fact(client, cid, key, value)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "LOW"
    assert body["next_action"] == "EXPLAIN_PROCEDURALLY_COMPLIANT_PRICE_REVIEW"


def test_e07_fixed_price_review_inside_fixed_period_is_challenged(client):
    cid = create_case(client, "Me han hecho una revisión de precio de la luz aunque mi contrato era fijo", "E07")
    fill_e07_notice(client, cid, kind="contractual_price_review", received=True, notice_date="2026-07-01", separate=True)
    post_fact(client, cid, "electricity.fixed_price_contract", True)
    post_fact(client, cid, "electricity.price_review_within_fixed_price_period", True)
    post_fact(client, cid, "electricity.price_review_formula_preagreed", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "PREPARE_E07_FIXED_PRICE_CHALLENGE"


def test_e07_no_preagreed_formula_is_reclassified_as_condition_change(client):
    cid = create_case(client, "Dicen que es una revisión de precio de electricidad pero no estaba en el contrato", "E07")
    fill_e07_notice(client, cid, kind="contractual_price_review", received=True, notice_date="2026-07-01", separate=True)
    post_fact(client, cid, "electricity.fixed_price_contract", False)
    post_fact(client, cid, "electricity.price_review_formula_preagreed", False)
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["viability"] == "RECLASSIFY"
    assert body["next_action"] == "RECLASSIFY_E07_CONDITION_CHANGE"


def test_e07_before_current_rule_is_legacy_review(client):
    cid = create_case(client, "Me cambiaron el precio de la luz sin avisar", "E07")
    post_fact(client, cid, "electricity.contract_change_effective_date", "2026-06-11")
    post_fact(client, cid, "electricity.contract_change_kind", "contract_condition_change")
    body = client.post(f"/api/cases/{cid}/diagnose").json()
    assert body["scope_status"] == "LEGACY_REVIEW"
    assert body["next_action"] == "HUMAN_REVIEW_LEGACY"
