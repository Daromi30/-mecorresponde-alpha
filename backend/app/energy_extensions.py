from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.common import FactValue
from .engine.e03 import evaluate_e03
from .engine.e05 import evaluate_e05
from .models import Action, Decision

_INSTALLED = False
_ORIGINAL_SEED = svc.seed_legal
_ORIGINAL_CREATE = svc.create_case
_ORIGINAL_PREPARE = svc.prepare_claim_package
_ORIGINAL_ANALYZE = svc.analyze_company_response
_ORIGINAL_NEXT_QUESTION = svc.next_question


def _value(facts: dict[str, FactValue], key: str, default=None):
    return facts[key].value if key in facts else default


def _ask(key: str, question: str, input_type: str, options: list[dict[str, str]] | None = None) -> dict:
    result = {"done": False, "question": question, "field": key, "input_type": input_type}
    if options:
        result["options"] = options
    return result


def _e03_question(facts: dict[str, FactValue]) -> dict:
    order = [
        ("electricity.switch_effective_date", "¿Qué día se hizo efectivo el cambio a la nueva comercializadora?", "date"),
        ("electricity.previous_supplier", "¿Cuál era tu comercializadora antes del cambio?", "text"),
        ("electricity.incoming_supplier", "¿A qué comercializadora te cambiaron?", "text"),
        ("electricity.possible_identity_theft", "¿Hay indicios de suplantación de identidad, por ejemplo datos o firma usados por otra persona?", "boolean"),
        ("electricity.switch_cups_correct", "¿El cambio se hizo sobre tu CUPS correcto? Si no lo sabes, indícalo.", "boolean_unknown"),
        ("electricity.express_consent_given", "¿Diste de forma expresa tu consentimiento para cambiar a esa comercializadora?", "boolean_unknown"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)
    if _value(facts, "electricity.possible_identity_theft") is True:
        return {"done": True, "question": None, "field": None}
    if "electricity.consent_evidence_status" not in facts:
        return _ask(
            "electricity.consent_evidence_status",
            "¿La nueva comercializadora te ha enseñado una grabación, firma o documento duradero que demuestre tu consentimiento expreso?",
            "choice",
            [
                {"value": "not_provided", "label": "No me han enseñado ninguna prueba"},
                {"value": "valid_durable_proof", "label": "Sí, hay una prueba que reconozco como válida"},
                {"value": "disputed_or_unclear", "label": "Hay algo, pero no lo reconozco o no está claro"},
            ],
        )
    if "electricity.unsolicited_supply_amount_paid" not in facts:
        return _ask(
            "electricity.unsolicited_supply_amount_paid",
            "¿Cuánto has pagado ya a la nueva comercializadora por ese suministro que consideras no solicitado? Si no has pagado nada, indica 0.",
            "money",
        )
    return {"done": True, "question": None, "field": None}


def _e05_question(facts: dict[str, FactValue]) -> dict:
    order = [
        ("electricity.consumer_natural_person", "¿El contrato de luz estaba a nombre de una persona física?", "boolean"),
        ("electricity.segment_2_0td", "¿El suministro estaba en el segmento tarifario 2.0TD?", "boolean"),
        ("electricity.termination_date", "¿Qué día terminó o cambiaste el contrato con esa comercializadora?", "date"),
        ("electricity.termination_penalty_amount", "¿Qué importe te han cobrado o exigido como penalización por cancelar/cambiar?", "money"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)
    if _value(facts, "electricity.consumer_natural_person") is False or _value(facts, "electricity.segment_2_0td") is False:
        return {"done": True, "question": None, "field": None}
    if "electricity.switch_to_pvpc_as_vulnerable" not in facts:
        return _ask(
            "electricity.switch_to_pvpc_as_vulnerable",
            "¿El cambio fue a PVPC acreditando los requisitos para consumidor vulnerable/bono social?",
            "boolean",
        )
    if _value(facts, "electricity.switch_to_pvpc_as_vulnerable") is True:
        return {"done": True, "question": None, "field": None}
    if "electricity.fixed_price_contract" not in facts:
        return _ask(
            "electricity.fixed_price_contract",
            "¿El contrato que cancelaste tenía un precio fijo de la energía?",
            "boolean",
        )
    if _value(facts, "electricity.fixed_price_contract") is True:
        if "electricity.before_first_annual_renewal" not in facts:
            return _ask(
                "electricity.before_first_annual_renewal",
                "¿Cancelaste antes de que llegara la primera prórroga anual del contrato?",
                "boolean",
            )
        if _value(facts, "electricity.before_first_annual_renewal") is True:
            if "electricity.supplier_provided_direct_loss_proof" not in facts:
                return _ask(
                    "electricity.supplier_provided_direct_loss_proof",
                    "¿La comercializadora te ha explicado y acreditado qué pérdida económica directa le causó tu cancelación?",
                    "boolean",
                )
            if "electricity.supplier_provided_penalty_calculation" not in facts:
                return _ask(
                    "electricity.supplier_provided_penalty_calculation",
                    "¿Te ha facilitado el cálculo o la base utilizada para obtener la penalización?",
                    "boolean",
                )
    return {"done": True, "question": None, "field": None}


def _next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    if family == "E03":
        return _e03_question(facts)
    if family == "E05":
        return _e05_question(facts)
    return _ORIGINAL_NEXT_QUESTION(facts, family)


def _seed_legal(db: Session):
    rules = _ORIGINAL_SEED(db)
    rules["ELEC_SWITCH_EXPRESS_CONSENT"] = svc._ensure_rule(
        db,
        "ELEC_SWITCH_EXPRESS_CONSENT",
        1,
        date(2026, 2, 12),
        "RD88_2026",
        "18.5-18.7 y 51.3",
        {"supplier_switch": True},
        {
            "express_consent_required": True,
            "durable_proof_retention_years": 5,
            "restore_previous_supplier_if_no_consent_or_wrong_cups": True,
            "no_payment_for_unsolicited_supply": True,
        },
        "El comercializador entrante debe asegurar el consentimiento expreso y conservarlo en soporte duradero al menos cinco años. Un cambio sin consentimiento o por CUPS incorrecto debe restituirse al comercializador saliente y contrato previo; no puede reclamarse pago por suministro no solicitado.",
    )
    rules["ELEC_TERMINATION_PENALTY_CURRENT"] = svc._ensure_rule(
        db,
        "ELEC_TERMINATION_PENALTY_CURRENT",
        1,
        date(2026, 6, 12),
        "RD88_2026",
        "28.3, 28.9 y DT 8ª",
        {"natural_person": True, "segment_2_0td": True},
        {
            "general_termination_penalty": 0,
            "exception": "fixed_price_before_first_annual_renewal",
            "exception_max_percent": 5,
            "supplier_bears_direct_loss_burden": True,
            "transitional_estimation_method": "change_of_supplier_measure_estimation_until_ministerial_order",
        },
        "Desde el 12/06/2026 la persona física 2.0TD puede rescindir sin penalización salvo contrato a precio fijo antes de la primera prórroga anual. En la excepción, la penalización exige daño al comercializador, queda limitada legalmente y la pérdida económica directa debe probarla la comercializadora. La DT 8ª fija un método transitorio de estimación mientras no se dicte la orden ministerial.",
    )
    return rules


def _create_case(db: Session, message: str):
    case = _ORIGINAL_CREATE(db, message)
    if case.family == "E03":
        case.title = "Cambio de comercializadora sin consentimiento"
        db.commit()
        db.refresh(case)
    elif case.family == "E05":
        case.title = "Penalización o permanencia al cancelar la luz"
        db.commit()
        db.refresh(case)
    return case


def _prepare_e03_claim(db: Session, case) -> dict[str, Any]:
    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing an automated E03 claim")
    facts = svc.latest_facts(db, case.id)
    result = evaluate_e03(facts)
    if result.next_action != "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION":
        raise ValueError("Current E03 action requires more information or human review")
    amount = round(float(decision.claimable_amount or 0.0), 2)
    old = _value(facts, "electricity.previous_supplier", "comercializadora anterior")
    new = _value(facts, "electricity.incoming_supplier", "comercializadora entrante")
    text = (
        f"Impugno el cambio de suministro desde {old} a {new} por falta de consentimiento expreso o por error en la identificación del punto, según los hechos confirmados del expediente. "
        "Solicito la restitución al comercializador saliente y al contrato previo conforme a los artículos 18 y 51.3 del RD 88/2026, así como el cese de cargos por suministro no solicitado."
    )
    if amount > 0:
        text += f" Solicito además la devolución de {amount:.2f} € ya pagados por el suministro no solicitado identificado en el expediente."
    payload = {
        "claim_type": "E03_UNAUTHORIZED_SWITCH_RESTORATION",
        "remedies": list(result.remedies),
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": [{
            "rule_id": "ELEC_SWITCH_EXPRESS_CONSENT",
            "article": "18.5-18.7 y 51.3",
            "source": "RD 88/2026",
        }],
        "text": text,
    }
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    svc.audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {
        "action_id": action.id,
        "amount": amount,
        "economic_value": decision.economic_value,
        "family": case.family,
    })
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}


def _prepare_claim_package(db: Session, case) -> dict[str, Any]:
    if case.family == "E03":
        return _prepare_e03_claim(db, case)
    if case.family != "E05":
        return _ORIGINAL_PREPARE(db, case)
    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing an automated E05 claim")
    facts = svc.latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )
    result = evaluate_e05(facts)
    if result.next_action != "PREPARE_E05_PENALTY_REFUND":
        raise ValueError("Current E05 action requires review rather than an automated claim")
    amount = round(float(decision.claimable_amount or 0.0), 2)
    if amount <= 0:
        raise ValueError("No verified termination penalty amount to recover")
    payload = {
        "claim_type": "E05_TERMINATION_PENALTY_REFUND",
        "remedies": list(result.remedies),
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": [{
            "rule_id": "ELEC_TERMINATION_PENALTY_CURRENT",
            "article": "28.3",
            "source": "RD 88/2026",
        }],
        "text": (
            f"Solicito la anulación y devolución de la penalización por rescisión de {amount:.2f} €. "
            "Soy persona física acogida al segmento 2.0TD y, conforme al artículo 28.3 del Real Decreto 88/2026, el contrato y sus prórrogas pueden rescindirse sin penalización salvo el supuesto excepcional de contrato a precio fijo antes de la primera prórroga anual, que no concurre según los hechos confirmados del expediente."
        ),
    }
    action = Action(case_id=case.id, type="SUBMIT_INITIAL_CLAIM", status="READY", payload_json=payload)
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    case.status = "READY_TO_SUBMIT"
    svc.audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {
        "action_id": action.id,
        "amount": amount,
        "economic_value": decision.economic_value,
        "family": case.family,
    })
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}


def _analyze_company_response(db: Session, case, text: str):
    result = _ORIGINAL_ANALYZE(db, case, text)
    mapping = {
        "FIXED_PRICE_FIRST_YEAR_ASSERTED": "company.asserts_fixed_price_first_year",
        "CUPS_CORRECT_ASSERTED": "company.asserts_correct_cups",
    }
    for argument in result.get("arguments", []):
        key = mapping.get(argument)
        if key:
            svc.upsert_fact(
                db, case, key, True,
                state="asserted", user_confirmed=False, created_by="company",
            )
    return result


def install_energy_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS.update({"E03": evaluate_e03, "E05": evaluate_e05})
    svc.FAMILY_RULES.update({
        "E03": ["ELEC_SWITCH_EXPRESS_CONSENT"],
        "E05": ["ELEC_TERMINATION_PENALTY_CURRENT"],
    })
    svc.next_question = _next_question
    svc.seed_legal = _seed_legal
    svc.create_case = _create_case
    svc.prepare_claim_package = _prepare_claim_package
    svc.analyze_company_response = _analyze_company_response
    _INSTALLED = True
