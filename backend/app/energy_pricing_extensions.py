from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.e01 import evaluate_e01
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
    result = {"done": False, "question": question, "field": key, "input_type": input_type}
    if options:
        result["options"] = options
    return result


def _e01_question(facts) -> dict:
    common = [
        ("electricity.consumer_natural_person", "¿El contrato de luz está a nombre de una persona física para uso particular?", "boolean"),
        ("electricity.market_type", "¿Tu contrato es de mercado libre o PVPC/precio regulado?", "choice"),
        ("electricity.pricing_issue_date", "¿Desde qué fecha o en qué factura detectaste el precio, tarifa o descuento incorrecto?", "date"),
        ("electricity.pricing_issue_type", "¿Qué no coincide con lo que contrataste o te ofrecieron?", "choice"),
        ("electricity.pricing_contract_or_offer_evidence_available", "¿Tienes contrato, oferta, email, captura o documento donde aparezcan las condiciones prometidas?", "boolean"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            if key == "electricity.market_type":
                return _ask(key, question, input_type, [
                    {"value": "free_market", "label": "Mercado libre"},
                    {"value": "pvpc", "label": "PVPC / precio regulado"},
                    {"value": "unknown", "label": "No lo sé"},
                ])
            if key == "electricity.pricing_issue_type":
                return _ask(key, question, input_type, [
                    {"value": "contracted_price_mismatch", "label": "Me aplican un precio distinto al contratado/ofertado"},
                    {"value": "tariff_mismatch", "label": "Me aplican otra tarifa/modalidad distinta"},
                    {"value": "discount_mismatch", "label": "No respetan el descuento o promoción"},
                    {"value": "other", "label": "Otro problema de precio"},
                ])
            return _ask(key, question, input_type)

    if _value(facts, "electricity.consumer_natural_person") is False:
        return {"done": True, "question": None, "field": None}
    if _value(facts, "electricity.market_type") != "free_market":
        return {"done": True, "question": None, "field": None}
    if _value(facts, "electricity.pricing_contract_or_offer_evidence_available") is False:
        return {"done": True, "question": None, "field": None}

    issue_type = _value(facts, "electricity.pricing_issue_type")
    if issue_type in {"contracted_price_mismatch", "tariff_mismatch"}:
        order = [
            ("electricity.pricing_promised_terms", "¿Qué precio o tarifa figura en la oferta/contrato? Copia el dato tal como aparece.", "text"),
            ("electricity.pricing_applied_terms", "¿Qué precio o tarifa te están aplicando realmente?", "text"),
            ("electricity.pricing_difference_confirmed", "Comparando los documentos, ¿confirmas que son distintos?", "boolean"),
        ]
        for key, question, input_type in order:
            if key not in facts:
                return _ask(key, question, input_type)
    elif issue_type == "discount_mismatch":
        if "electricity.discount_duration_and_terms_disclosed" not in facts:
            return _ask(
                "electricity.discount_duration_and_terms_disclosed",
                "¿La oferta o contrato indica claramente cuánto dura el descuento y sobre qué precio/conceptos se aplica?",
                "boolean_unknown",
            )
        if "electricity.discount_application_matches_promised_terms" not in facts:
            return _ask(
                "electricity.discount_application_matches_promised_terms",
                "¿El descuento que realmente te han aplicado coincide con esas condiciones prometidas?",
                "boolean_unknown",
            )
    return {"done": True, "question": None, "field": None}


def _next_question(facts, family: str | None):
    if family == "E01":
        return _e01_question(facts)
    return _PREVIOUS_NEXT_QUESTION(facts, family)


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    rules["ELEC_PRICING_TERMS_CURRENT"] = svc._ensure_rule(
        db,
        "ELEC_PRICING_TERMS_CURRENT",
        1,
        date(2026, 6, 12),
        "RD88_2026",
        "30.1.i-k, q, u y w; DF 9.4",
        {"free_market_pricing_or_discount_issue": True},
        {
            "pricing_terms_must_be_clear": True,
            "promotional_discount_duration_and_basis_must_be_express": True,
            "fixed_price_contract_must_state_power_and_energy_prices": True,
            "billing_error_correction_mechanism_required": True,
        },
        "En mercado libre, el contrato debe especificar de forma clara las condiciones económicas, las reglas de revisión y la duración y base de los descuentos promocionales; para precio fijo debe expresar los precios de potencia y energía.",
    )
    rules["CONSUMER_OFFER_BINDING"] = svc._ensure_rule(
        db,
        "CONSUMER_OFFER_BINDING",
        1,
        date(2007, 12, 1),
        "TRLGDCU",
        "61",
        {"consumer_offer_or_promotion": True},
        {"offered_economic_terms_are_enforceable": True},
        "El contenido económico de la oferta, promoción o publicidad es exigible por la persona consumidora y se integra en el contrato en los términos del artículo 61 TRLGDCU.",
    )
    return rules


def _create_case(db: Session, message: str):
    case = _PREVIOUS_CREATE(db, message)
    if case.family == "E01":
        case.title = "Precio, tarifa o descuento eléctrico distinto de lo contratado"
        db.commit()
        db.refresh(case)
    return case


def _prepare_claim_package(db: Session, case):
    if case.family != "E01":
        return _PREVIOUS_PREPARE(db, case)

    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support an automated E01 action")

    facts = svc.latest_facts(db, case.id)
    result = evaluate_e01(facts)
    if result.next_action == "PREPARE_E01_PRICING_CORRECTION":
        claim_type = "E01_CONTRACTED_PRICE_OR_TARIFF_CORRECTION"
        text = (
            "Solicito que se aplique el precio o modalidad económica efectivamente ofertada/contratada y que se revisen las facturas del periodo afectado. "
            "El artículo 30 del RD 88/2026 exige condiciones económicas claras y transparentes y el artículo 61 del TRLGDCU hace exigible el contenido de la oferta o promoción. "
            "La cuantía concreta de cualquier devolución deberá calcularse con las facturas, consumos y precios verificables."
        )
    elif result.next_action == "PREPARE_E01_DISCOUNT_CORRECTION":
        claim_type = "E01_PROMOTIONAL_DISCOUNT_CORRECTION"
        text = (
            "Solicito que se respeten las condiciones del descuento/promoción ofertado y que se revisen las facturas afectadas. "
            "El artículo 30.1.k del RD 88/2026 exige indicar expresamente la duración de los descuentos promocionales y los términos o precios sobre los que se aplican, y el artículo 61 del TRLGDCU integra la oferta en el contrato. "
            "La devolución exacta, si procede, se calculará únicamente con documentación de facturación verificable."
        )
    else:
        raise ValueError("Current E01 action requires information, explanation or human review rather than a claim")

    payload = {
        "claim_type": claim_type,
        "remedies": list(result.remedies),
        "amount": 0.0,
        "amount_status": "REQUIRES_VERIFIED_BILLING_CALCULATION",
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": [
            {"rule_id": "ELEC_PRICING_TERMS_CURRENT", "article": "30.1.i-k, q, u y w", "source": "RD 88/2026"},
            {"rule_id": "CONSUMER_OFFER_BINDING", "article": "61", "source": "TRLGDCU"},
        ],
        "text": text,
    }
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    svc.audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {
        "action_id": action.id,
        "amount": 0.0,
        "amount_status": payload["amount_status"],
        "economic_value": decision.economic_value,
        "family": case.family,
    })
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}


def _analyze_company_response(db: Session, case, text: str):
    result = _PREVIOUS_ANALYZE(db, case, text)
    if "PRICING_MATCHES_CONTRACT_ASSERTED" in result.get("arguments", []):
        svc.upsert_fact(
            db,
            case,
            "company.asserts_pricing_matches_contract",
            True,
            state="asserted",
            user_confirmed=False,
            created_by="company",
        )
    return result


def install_energy_pricing_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["E01"] = evaluate_e01
    svc.FAMILY_RULES["E01"] = ["ELEC_PRICING_TERMS_CURRENT", "CONSUMER_OFFER_BINDING"]
    svc.next_question = _next_question
    svc.seed_legal = _seed_legal
    svc.create_case = _create_case
    svc.prepare_claim_package = _prepare_claim_package
    svc.analyze_company_response = _analyze_company_response
    _INSTALLED = True
