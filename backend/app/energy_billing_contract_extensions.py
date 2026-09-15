from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.e06 import evaluate_e06
from .engine.e07 import evaluate_e07
from .models import Action, Decision

_INSTALLED = False
_PREVIOUS_SEED = svc.seed_legal
_PREVIOUS_CREATE = svc.create_case
_PREVIOUS_PREPARE = svc.prepare_claim_package
_PREVIOUS_ANALYZE = svc.analyze_company_response
_PREVIOUS_NEXT_QUESTION = svc.next_question


def _value(facts, key, default=None):
    return facts[key].value if key in facts else default


def _ask(key: str, question: str, input_type: str, options: list[dict[str, str]] | None = None):
    payload = {"done": False, "question": question, "field": key, "input_type": input_type}
    if options:
        payload["options"] = options
    return payload


def _e06_question(facts) -> dict:
    order = [
        ("electricity.reading_issue_invoice_date", "¿De qué fecha es la factura o regularización que quieres revisar?", "date"),
        (
            "electricity.meter_fraud_tampering_or_complex_technical_issue",
            "¿La compañía habla de manipulación, fraude del contador o existe una controversia técnica compleja sobre el equipo de medida?",
            "boolean",
        ),
        (
            "electricity.reading_issue_type",
            "¿Qué ha ocurrido principalmente?",
            "choice",
        ),
    ]
    for key, question, input_type in order:
        if key not in facts:
            if key == "electricity.reading_issue_type":
                return _ask(key, question, input_type, [
                    {"value": "estimated_reading", "label": "Me han facturado con una lectura/consumo estimado"},
                    {"value": "underbilling_regularization", "label": "Me regularizan ahora porque antes facturaron de menos"},
                    {"value": "overbilling_regularization", "label": "Me regularizan porque antes facturaron de más"},
                    {"value": "other", "label": "Otro problema de lectura o contador"},
                ])
            return _ask(key, question, input_type)

    if _value(facts, "electricity.meter_fraud_tampering_or_complex_technical_issue") is True:
        return {"done": True, "question": None, "field": None}

    issue_type = _value(facts, "electricity.reading_issue_type")
    if issue_type == "underbilling_regularization":
        if "electricity.regularization_period_months" not in facts:
            return _ask(
                "electricity.regularization_period_months",
                "¿Cuántos meses anteriores pretende corregir la regularización?",
                "number",
            )
        if "electricity.regularization_amount" not in facts:
            return _ask(
                "electricity.regularization_amount",
                "¿Qué importe total te reclaman en esa regularización? Si no está claro, indica 0 y lo revisaremos con el desglose.",
                "money",
            )
        return {"done": True, "question": None, "field": None}

    if issue_type == "overbilling_regularization":
        if "electricity.regularization_amount" not in facts:
            return _ask("electricity.regularization_amount", "¿Qué importe está afectado por la regularización?", "money")
        return {"done": True, "question": None, "field": None}

    if issue_type == "estimated_reading":
        if "electricity.estimated_reading_reason" not in facts:
            return _ask(
                "electricity.estimated_reading_reason",
                "¿Por qué dice la compañía que tuvo que estimar la lectura?",
                "choice",
                [
                    {"value": "remote_reading_failure", "label": "Falló la lectura remota"},
                    {"value": "no_meter_access", "label": "No pudieron acceder al contador"},
                    {"value": "other_or_unknown", "label": "Otro motivo o no lo sé"},
                ],
            )
        reason = _value(facts, "electricity.estimated_reading_reason")
        if reason == "remote_reading_failure" and "electricity.real_reading_obtained_within_bimonthly_cycle" not in facts:
            return _ask(
                "electricity.real_reading_obtained_within_bimonthly_cycle",
                "¿Se obtuvo finalmente una lectura real dentro de los dos meses siguientes?",
                "boolean_unknown",
            )
        if reason == "no_meter_access":
            if "electricity.impossible_reading_notice_received" not in facts:
                return _ask(
                    "electricity.impossible_reading_notice_received",
                    "¿Te dejaron o enviaron un aviso de imposible lectura indicando cómo facilitar tu lectura?",
                    "boolean_unknown",
                )
            if _value(facts, "electricity.impossible_reading_notice_received") is True and "electricity.user_supplied_reading_within_10_business_days" not in facts:
                return _ask(
                    "electricity.user_supplied_reading_within_10_business_days",
                    "¿Facilitaste tú la lectura dentro de los diez días hábiles siguientes al aviso?",
                    "boolean_unknown",
                )
        return {"done": True, "question": None, "field": None}

    return {"done": True, "question": None, "field": None}


def _e07_question(facts) -> dict:
    if "electricity.contract_change_effective_date" not in facts:
        return _ask("electricity.contract_change_effective_date", "¿Desde qué fecha empezó o iba a empezar a aplicarse el cambio de precio o condiciones?", "date")
    if "electricity.contract_change_kind" not in facts:
        return _ask(
            "electricity.contract_change_kind",
            "¿El cambio estaba ya previsto mediante una fórmula de revisión del contrato o es una modificación nueva de las condiciones?",
            "choice",
            [
                {"value": "contract_condition_change", "label": "Es una modificación nueva de precio/condiciones"},
                {"value": "contractual_price_review", "label": "Dicen que es una revisión prevista por el contrato"},
            ],
        )
    if "electricity.change_notice_received" not in facts:
        return _ask("electricity.change_notice_received", "¿Recibiste un aviso previo por escrito sobre el cambio?", "boolean")
    if _value(facts, "electricity.change_notice_received") is True:
        if "electricity.change_notice_date" not in facts:
            return _ask("electricity.change_notice_date", "¿Qué fecha tenía o cuándo recibiste ese aviso?", "date")
        if "electricity.change_notice_separate_from_invoice" not in facts:
            return _ask(
                "electricity.change_notice_separate_from_invoice",
                "¿El aviso llegó separado de la factura, como comunicación específica?",
                "boolean",
            )

    kind = _value(facts, "electricity.contract_change_kind")
    if kind == "contract_condition_change":
        if "electricity.notice_informed_free_termination_right" not in facts:
            return _ask(
                "electricity.notice_informed_free_termination_right",
                "¿El aviso decía claramente que podías rescindir el contrato sin coste por la modificación?",
                "boolean_unknown",
            )
        return {"done": True, "question": None, "field": None}

    if kind == "contractual_price_review":
        if "electricity.fixed_price_contract" not in facts:
            return _ask("electricity.fixed_price_contract", "¿Tu contrato era a precio fijo durante el periodo afectado?", "boolean_unknown")
        if _value(facts, "electricity.fixed_price_contract") is True and "electricity.price_review_within_fixed_price_period" not in facts:
            return _ask(
                "electricity.price_review_within_fixed_price_period",
                "¿La revisión pretende aplicarse antes de terminar el periodo durante el que el precio estaba fijado?",
                "boolean_unknown",
            )
        if "electricity.price_review_formula_preagreed" not in facts:
            return _ask(
                "electricity.price_review_formula_preagreed",
                "¿El contrato original incluía una cláusula transparente con parámetros o fórmula para calcular esa revisión?",
                "boolean_unknown",
            )
        if _value(facts, "electricity.price_review_formula_preagreed") is True:
            if "electricity.price_review_reasons_scope_explained" not in facts:
                return _ask(
                    "electricity.price_review_reasons_scope_explained",
                    "¿La comunicación explica las razones, condiciones previas y alcance de la revisión?",
                    "boolean_unknown",
                )
            if "electricity.price_review_transitional_content_complete" not in facts:
                return _ask(
                    "electricity.price_review_transitional_content_complete",
                    "¿Incluye fecha de aplicación, comparación de precios antes/después y comparación del coste anual estimado?",
                    "boolean_unknown",
                )
        return {"done": True, "question": None, "field": None}

    return {"done": True, "question": None, "field": None}


def _next_question(facts, family: str | None):
    if family == "E06":
        return _e06_question(facts)
    if family == "E07":
        return _e07_question(facts)
    return _PREVIOUS_NEXT_QUESTION(facts, family)


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    rules["ELEC_READING_BILLING_CURRENT"] = svc._ensure_rule(
        db,
        "ELEC_READING_BILLING_CURRENT",
        1,
        date(2026, 6, 12),
        "RD88_2026",
        "43-45 y DF 9.4",
        {"reading_or_regularization_issue": True},
        {
            "remote_failure_requires_real_reading_at_least_bimonthly": True,
            "no_access_estimate_requires_notice_and_no_user_reading_within_10_business_days": True,
            "underbilling_correction_period_max_months": 12,
            "overbilling_refund_rule": "handled_by_E02-A",
        },
        "Desde el 12/06/2026 los artículos 43 a 45 regulan lectura, estimaciones y correcciones de facturación. E06 automatiza solo supuestos claros y remite fraude/manipulación o controversias técnicas a revisión humana.",
    )
    rules["ELEC_CONTRACT_CHANGE_NOTICE_CURRENT"] = svc._ensure_rule(
        db,
        "ELEC_CONTRACT_CHANGE_NOTICE_CURRENT",
        1,
        date(2026, 6, 12),
        "RD88_2026",
        "6.1.m-n, 30.1.i-j y DT 7ª",
        {"contract_change_or_price_review": True},
        {
            "condition_change_notice_days": 30,
            "condition_change_notice_separate_from_invoice": True,
            "condition_change_must_disclose_free_termination": True,
            "contractual_price_review_notice_days": 30,
            "price_review_must_explain_reasons_and_scope": True,
            "transitional_price_review_comparison_content": True,
            "review_clauses_not_applicable_to_fixed_price_contracts": True,
        },
        "Las modificaciones de condiciones y las revisiones de precio previstas contractualmente son supuestos distintos. La primera exige aviso previo e información de rescisión sin coste; la segunda exige además trazabilidad de la fórmula y comunicación específica con el contenido comparativo aplicable.",
    )
    return rules


def _create_case(db: Session, message: str):
    case = _PREVIOUS_CREATE(db, message)
    titles = {
        "E06": "Lectura estimada o regularización de consumo",
        "E07": "Cambio de precio o condiciones del contrato eléctrico",
    }
    if case.family in titles:
        case.title = titles[case.family]
        db.commit()
        db.refresh(case)
    return case


def _latest_decision(db: Session, case):
    return db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()


def _store_claim(db: Session, case, payload: dict[str, Any]):
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    svc.audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {
        "action_id": action.id,
        "amount": payload.get("amount", 0.0),
        "amount_status": payload.get("amount_status"),
        "economic_value": payload.get("economic_value"),
        "family": case.family,
    })
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}


def _prepare_e06(db: Session, case):
    decision = _latest_decision(db, case)
    if not decision or decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support an automated E06 action")
    facts = svc.latest_facts(db, case.id)
    result = evaluate_e06(facts)
    if result.next_action == "PREPARE_E06_READING_CORRECTION":
        text = (
            "Solicito la revisión de la lectura utilizada, la obtención o utilización de una lectura real verificable y la refacturación que corresponda conforme a los artículos 43 a 45 del RD 88/2026. "
            "La reclamación se limita al procedimiento de lectura/facturación acreditado y no presupone una cuantía monetaria que no haya sido calculada con datos verificables."
        )
        claim_type = "E06_READING_CORRECTION"
        amount_status = "PENDING_VERIFIED_REBILLING"
    elif result.next_action == "PREPARE_E06_LIMIT_REGULARIZATION":
        months = _value(facts, "electricity.regularization_period_months")
        text = (
            f"La regularización pretende rectificar {months} meses. Solicito que se limite el periodo corregido al máximo de un año previsto en el artículo 45.2 del RD 88/2026 y que se facilite un desglose mensual reproducible del nuevo cálculo. "
            "No fijo automáticamente una cantidad a devolver o dejar de pagar sin ese desglose."
        )
        claim_type = "E06_LIMIT_UNDERBILLING_REGULARIZATION"
        amount_status = "REQUIRES_MONTHLY_BREAKDOWN"
    else:
        raise ValueError("Current E06 action requires information or human review rather than a claim")
    return _store_claim(db, case, {
        "claim_type": claim_type,
        "remedies": list(result.remedies),
        "amount": 0.0,
        "amount_status": amount_status,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": [{"rule_id": "ELEC_READING_BILLING_CURRENT", "article": "43-45", "source": "RD 88/2026"}],
        "text": text,
    })


def _prepare_e07(db: Session, case):
    decision = _latest_decision(db, case)
    if not decision or decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support an automated E07 action")
    facts = svc.latest_facts(db, case.id)
    result = evaluate_e07(facts)
    if result.next_action == "PREPARE_E07_CHANGE_CHALLENGE":
        text = (
            "Impugno la aplicación de la modificación de condiciones por no constar una comunicación que cumpla íntegramente el artículo 6.1.m del RD 88/2026. "
            "Solicito una comunicación previa válida y confirmación de mi derecho a rescindir sin coste. Si existe una diferencia económica ya facturada, deberá cuantificarse con las facturas y precios verificables antes de reclamar un importe concreto."
        )
        claim_type = "E07_CONTRACT_CHANGE_NOTICE_CHALLENGE"
    elif result.next_action == "PREPARE_E07_PRICE_REVIEW_CHALLENGE":
        text = (
            "Impugno la aplicación de la revisión de precio hasta que se acredite una comunicación conforme al artículo 6.1.n y a la disposición transitoria séptima del RD 88/2026, incluyendo antelación, razones y alcance, comparación de precios y estimación comparativa del coste anual. "
            "Cualquier devolución monetaria se calculará separadamente si las facturas prueban un exceso."
        )
        claim_type = "E07_PRICE_REVIEW_NOTICE_CHALLENGE"
    elif result.next_action == "PREPARE_E07_FIXED_PRICE_CHALLENGE":
        text = (
            "Impugno la revisión aplicada durante el periodo de precio fijo del contrato. Solicito que se respete el precio pactado o que se identifique la base contractual y normativa específica que permitiría el cambio, teniendo en cuenta que el artículo 30.1.i del RD 88/2026 excluye las cláusulas de revisión en contratos a precio fijo."
        )
        claim_type = "E07_FIXED_PRICE_REVIEW_CHALLENGE"
    else:
        raise ValueError("Current E07 action requires information, reclassification or explanation rather than a claim")
    return _store_claim(db, case, {
        "claim_type": claim_type,
        "remedies": list(result.remedies),
        "amount": 0.0,
        "amount_status": "MONETARY_EFFECT_REQUIRES_VERIFIED_INVOICES",
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": [{"rule_id": "ELEC_CONTRACT_CHANGE_NOTICE_CURRENT", "article": "6.1.m-n, 30.1.i-j, DT 7ª", "source": "RD 88/2026"}],
        "text": text,
    })


def _prepare_claim_package(db: Session, case):
    if case.family == "E06":
        return _prepare_e06(db, case)
    if case.family == "E07":
        return _prepare_e07(db, case)
    return _PREVIOUS_PREPARE(db, case)


def _analyze_company_response(db: Session, case, text: str):
    result = _PREVIOUS_ANALYZE(db, case, text)
    mapping = {
        "ESTIMATE_ALLOWED_ASSERTED": "company.asserts_estimate_allowed",
        "NOTICE_COMPLIANT_ASSERTED": "company.asserts_notice_compliant",
        "CONTRACTUAL_PRICE_FORMULA_ASSERTED": "company.asserts_contractual_price_formula",
    }
    for argument in result.get("arguments", []):
        key = mapping.get(argument)
        if key:
            svc.upsert_fact(
                db,
                case,
                key,
                True,
                state="asserted",
                user_confirmed=False,
                created_by="company",
            )
    return result


def install_energy_billing_contract_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS.update({"E06": evaluate_e06, "E07": evaluate_e07})
    svc.FAMILY_RULES.update({
        "E06": ["ELEC_READING_BILLING_CURRENT"],
        "E07": ["ELEC_CONTRACT_CHANGE_NOTICE_CURRENT"],
    })
    svc.next_question = _next_question
    svc.seed_legal = _seed_legal
    svc.create_case = _create_case
    svc.prepare_claim_package = _prepare_claim_package
    svc.analyze_company_response = _analyze_company_response
    _INSTALLED = True
