from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import get_args

from sqlalchemy import func, select

from app import services_v2 as svc
from app.engine.gateway import DeterministicAlphaGateway
from app.engine.model_contracts import CompanyArgument
from app.models import AIRun, Action, Case, Communication, Evidence, Fact
from app.reviews import HumanReview


ARGUMENT_CASES = [
    ("INDEPENDENT_ADDON_CONTRACT", "El mantenimiento es un contrato independiente.", "company.asserts_independent_addon_contract"),
    ("EXPRESS_KEEP_REQUEST", "Usted solicitó mantener el servicio.", "company.asserts_keep_request"),
    ("CONSENT_EVIDENCE", "Consta su consentimiento expreso.", "company.asserts_consent"),
    ("CUPS_CORRECT_ASSERTED", "El CUPS es correcto.", "company.asserts_correct_cups"),
    ("PRICING_MATCHES_CONTRACT_ASSERTED", "El precio coincide con el contrato.", "company.asserts_pricing_matches_contract"),
    ("ESTIMATE_ALLOWED_ASSERTED", "La estimación era procedente.", "company.asserts_estimate_allowed"),
    ("NOTICE_COMPLIANT_ASSERTED", "Avisamos con un mes de antelación.", "company.asserts_notice_compliant"),
    ("CONTRACTUAL_PRICE_FORMULA_ASSERTED", "Revisión prevista en el contrato.", "company.asserts_contractual_price_formula"),
    ("CORRECT_AMOUNT_DISPUTED", "Facturación correcta.", "company.asserts_correct_amount"),
    ("DIFFERENT_DEBTS", "Los cargos corresponden a facturas distintas.", "company.asserts_different_debts"),
    ("FIXED_PRICE_FIRST_YEAR_ASSERTED", "Era un contrato a precio fijo durante el primer año.", "company.asserts_fixed_price_first_year"),
    ("MISUSE_OR_ACCIDENTAL_DAMAGE", "La avería se debe a mal uso.", "company.asserts_misuse"),
    ("OUTSIDE_LEGAL_GUARANTEE", "El producto está fuera de garantía.", "company.asserts_outside_guarantee"),
    ("REFER_TO_MANUFACTURER", "Diríjase al fabricante.", "company.redirects_to_manufacturer"),
    ("GOODS_MATCH_CONTRACT_ASSERTED", "El producto coincide con lo pedido.", "company.asserts_goods_match_contract"),
    ("DELIVERY_PROOF_ASSERTED", "El pedido consta como entregado.", "company.asserts_delivered"),
    ("WITHDRAWAL_LATE_ASSERTED", "Desistimiento fuera de plazo.", "company.asserts_withdrawal_late"),
    ("WITHDRAWAL_EXCEPTION_ASSERTED", "El producto está excluido del desistimiento.", "company.asserts_withdrawal_exception"),
    ("INTERNET_INTERRUPTION_COMPENSATION_APPLIED_ASSERTED", "La compensación ya aplicada consta en su factura.", "company.asserts_internet_interruption_compensation_applied"),
    ("FLIGHT_REFUND_ALREADY_PAID_ASSERTED", "Ya hemos reembolsado el billete.", "company.asserts_flight_refund_already_paid"),
    ("DENIED_BOARDING_COMPENSATION_PAID_ASSERTED", "La compensación por denegación ya fue pagada.", "company.asserts_denied_boarding_compensation_paid"),
    ("PAYMENT_AUTHENTICATED_ASSERTED", "La operación fue autenticada.", "company.asserts_payment_authenticated"),
    ("ARTICLE_48_4_EXCEPTION_ASSERTED", "Usted consintió el adeudo y recibió aviso previo con cuatro semanas.", "company.asserts_article_48_4_exception"),
    ("BANK_FEE_REQUESTED_AND_PROVIDED_ASSERTED", "El servicio fue solicitado y efectivamente prestado.", "company.asserts_bank_fee_requested_and_provided"),
    ("RENT_DEPOSIT_DEDUCTIONS_ASSERTED", "Descontamos de la fianza por daños en la vivienda.", "company.asserts_rent_deposit_deductions"),
    ("INSURANCE_MINIMUM_PAYMENT_PAID_ASSERTED", "El importe mínimo ya pagado consta en el expediente.", "company.asserts_insurance_minimum_payment_paid"),
    ("INSURANCE_NONRENEWAL_LATE_ASSERTED", "La comunicación de no renovación está fuera de plazo.", "company.asserts_insurance_nonrenewal_late"),
]


FAMILY_DENIALS = {
    "B01": ("La operación fue autenticada.", "company.asserts_payment_authenticated"),
    "B02": ("Usted consintió el adeudo y recibió aviso previo con cuatro semanas.", "company.asserts_article_48_4_exception"),
    "B03": ("El servicio fue solicitado y efectivamente prestado.", "company.asserts_bank_fee_requested_and_provided"),
    "R01": ("Descontamos de la fianza por daños en la vivienda.", "company.asserts_rent_deposit_deductions"),
    "S01": ("El importe mínimo ya pagado consta en el expediente.", "company.asserts_insurance_minimum_payment_paid"),
    "S02": ("La comunicación de no renovación está fuera de plazo.", "company.asserts_insurance_nonrenewal_late"),
    "E01": ("El precio coincide con el contrato.", "company.asserts_pricing_matches_contract"),
    "E02-A": ("Facturación correcta.", "company.asserts_correct_amount"),
    "E02-B": ("Los cargos corresponden a facturas distintas.", "company.asserts_different_debts"),
    "E03": ("El CUPS es correcto.", "company.asserts_correct_cups"),
    "E04-A": ("Consta su consentimiento expreso.", "company.asserts_consent"),
    "E04-B": ("El mantenimiento es un contrato independiente.", "company.asserts_independent_addon_contract"),
    "E05": ("Era un contrato a precio fijo durante el primer año.", "company.asserts_fixed_price_first_year"),
    "E06": ("La estimación era procedente.", "company.asserts_estimate_allowed"),
    "E07": ("Avisamos con un mes de antelación.", "company.asserts_notice_compliant"),
    "C01": ("La avería se debe a mal uso.", "company.asserts_misuse"),
    "C02": ("El producto está fuera de garantía.", "company.asserts_outside_guarantee"),
    "C03": ("El producto coincide con lo pedido.", "company.asserts_goods_match_contract"),
    "C04": ("El pedido consta como entregado.", "company.asserts_delivered"),
    "C05": ("Desistimiento fuera de plazo.", "company.asserts_withdrawal_late"),
    "T01": ("La compensación ya aplicada consta en su factura.", "company.asserts_internet_interruption_compensation_applied"),
    "T02": ("Avisamos con un mes de antelación.", "company.asserts_notice_compliant"),
    "V01": ("Ya hemos reembolsado el billete.", "company.asserts_flight_refund_already_paid"),
    "V02": ("Ya hemos reembolsado el billete.", "company.asserts_flight_refund_already_paid"),
    "V03": ("La compensación por denegación ya fue pagada.", "company.asserts_denied_boarding_compensation_paid"),
}


_matrix_path = Path(__file__).with_name("test_beta_acceptance_matrix.py")
_spec = importlib.util.spec_from_file_location("mcr_beta_acceptance_matrix_argument_audit", _matrix_path)
assert _spec and _spec.loader
_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_matrix)
SCENARIOS = _matrix.SCENARIOS


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _submitted_case(client, family: str, scenario: dict) -> str:
    created = client.post("/api/cases", json={"message": scenario["message"]})
    assert created.status_code == 200, f"{family}: {created.text}"
    body = created.json()
    assert body["family"] == family
    case_id = body["id"]

    for key, value in scenario["facts"].items():
        _fact(client, case_id, key, value)

    charges = scenario.get("charges")
    if charges:
        response = client.post(f"/api/cases/{case_id}/charges", json={"charges": charges})
        assert response.status_code == 200, f"{family}: {response.text}"

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, f"{family}: {diagnosis.text}"
    assert diagnosis.json()["viability"] == "HIGH", (family, diagnosis.json())

    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, f"{family}: {prepared.text}"

    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-10",
            "channel": "web_form",
            "reference_number": f"ARG-AUDIT-{family}",
        },
    )
    assert submitted.status_code == 200, f"{family}: {submitted.text}"
    return case_id


def test_every_permitted_company_argument_has_an_explicit_company_fact_mapping_and_provenance(db):
    permitted = set(get_args(CompanyArgument))
    covered = {code for code, _, _ in ARGUMENT_CASES}
    assert covered == permitted

    parser = DeterministicAlphaGateway()
    for code, text, fact_key in ARGUMENT_CASES:
        parsed = parser.analyze_response(text)
        assert parsed == {"type": "DENIAL", "arguments": [code]}, (code, parsed)

        case = Case(status="WAITING_RESPONSE", vertical="electricity", family="E04-B", title=f"audit-{code}")
        db.add(case)
        db.commit()
        db.refresh(case)

        result = svc.analyze_company_response(db, case, text)
        assert result == parsed
        db.refresh(case)
        assert case.status == "RESPONSE_RECEIVED", code

        company_fact = db.scalars(
            select(Fact)
            .where(Fact.case_id == case.id, Fact.key == fact_key)
            .order_by(Fact.created_at.desc())
        ).first()
        assert company_fact is not None, (code, fact_key)
        assert company_fact.value_json == {"value": True}
        assert company_fact.state == "asserted"
        assert company_fact.user_confirmed is False
        assert company_fact.created_by == "company"
        assert company_fact.key.startswith("company.")

        evidence = db.scalars(
            select(Evidence).where(Evidence.case_id == case.id, Evidence.fact_id == company_fact.id)
        ).first()
        assert evidence is not None, code
        assert evidence.source_type == "company"

        run = db.scalars(
            select(AIRun)
            .where(AIRun.case_id == case.id, AIRun.task == "analyze_response")
            .order_by(AIRun.created_at.desc())
        ).first()
        assert run is not None, code
        assert code in (run.structured_output or {}).get("arguments", [])

        inbound = db.scalars(
            select(Communication)
            .where(Communication.case_id == case.id, Communication.direction == "INBOUND")
            .order_by(Communication.received_at.desc())
        ).first()
        assert inbound is not None, code
        assert inbound.body == text


def test_every_beta_family_keeps_denial_in_post_response_phase_and_blocks_second_initial_claim(client, db):
    assert set(FAMILY_DENIALS) == set(SCENARIOS)

    for family, scenario in SCENARIOS.items():
        case_id = _submitted_case(client, family, scenario)
        text, fact_key = FAMILY_DENIALS[family]

        response = client.post(
            f"/api/cases/{case_id}/responses/evidenced",
            json={
                "text": text,
                "received_on": "2026-09-11",
                "channel": "email",
                "reference_number": f"RESP-ARG-AUDIT-{family}",
            },
        )
        assert response.status_code == 200, f"{family}: {response.text}"
        body = response.json()
        assert body["analysis"]["type"] == "DENIAL", (family, body)
        assert body["analysis"]["arguments"], (family, body)
        assert body["case_status"] == "HUMAN_REVIEW", (family, body)

        db.expire_all()
        case = db.get(Case, case_id)
        assert case is not None
        assert case.status == "HUMAN_REVIEW", family

        company_fact = db.scalars(
            select(Fact)
            .where(Fact.case_id == case_id, Fact.key == fact_key)
            .order_by(Fact.created_at.desc())
        ).first()
        assert company_fact is not None, (family, fact_key)
        assert company_fact.state == "asserted"
        assert company_fact.user_confirmed is False
        assert company_fact.created_by == "company"

        evidence = db.scalars(
            select(Evidence).where(Evidence.case_id == case_id, Evidence.fact_id == company_fact.id)
        ).first()
        assert evidence is not None and evidence.source_type == "company", family

        current = db.get(Action, case.current_action_id)
        assert current is not None, family
        assert current.type == "HUMAN_REVIEW", (family, current.type)
        assert current.status == "OPEN", (family, current.status)
        assert (current.payload_json or {}).get("phase") == "POST_RESPONSE_ESCALATION", (family, current.payload_json)
        protected_action_id = current.id

        open_review = db.scalars(
            select(HumanReview).where(
                HumanReview.case_id == case_id,
                HumanReview.status == "OPEN",
                HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            )
        ).first()
        assert open_review is not None, family

        ready_initial_actions = db.scalar(
            select(func.count())
            .select_from(Action)
            .where(
                Action.case_id == case_id,
                Action.type == "SUBMIT_INITIAL_CLAIM",
                Action.status == "READY",
            )
        )
        assert int(ready_initial_actions or 0) == 0, family

        serialized = str(current.payload_json or {}).lower()
        for prohibited in (
            "court",
            "tribunal",
            "arbit",
            "regulator",
            "authority",
            "deadline",
            "success_probability",
            "probabilidad",
        ):
            assert prohibited not in serialized, (family, prohibited, current.payload_json)

        repeat_prepare = client.post(f"/api/cases/{case_id}/prepare-claim")
        assert repeat_prepare.status_code in {409, 422}, (family, repeat_prepare.status_code, repeat_prepare.text)
        db.expire_all()
        case_after = db.get(Case, case_id)
        assert case_after is not None
        assert case_after.status == "HUMAN_REVIEW", family
        assert case_after.current_action_id == protected_action_id, family
