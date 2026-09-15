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


def _ask(key: str, question: str, input_type: str, options: list[dict[str, str]] | None = None):
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
        ("electricity.switch_cups_correct", "¿El cambio se hizo sobre tu CUPS correcto? Si no lo sabes, marca «No lo sé».", "boolean_unknown"),
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
        ("electricity.termination_date", "¿En qué fecha cancelaste el contrato o cambiaste de comercializadora?", "date"),
        ("electricity.contract_holder_is_natural_person", "¿El titular del contrato es una persona física?", "boolean"),
        ("electricity.tariff_is_2_0td", "¿El suministro está en el segmento tarifario 2.0TD? Suele aparecer en la factura.", "boolean_unknown"),
        ("electricity.termination_penalty_charged", "¿Qué importe te han cobrado o pretenden cobrar como penalización por cancelar/cambiarte?", "money"),
        ("electricity.contract_is_fixed_price", "¿El contrato era a precio fijo?", "boolean_unknown"),
        ("electricity.first_annual_renewal_already_occurred", "Cuando cancelaste, ¿ya había pasado la primera renovación anual del contrato?", "boolean_unknown"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)

    if _value(facts, "electricity.contract_holder_is_natural_person") is False or _value(facts, "electricity.tariff_is_2_0td") is False:
        return {"done": True, "question": None, "field": None}

    if _value(facts, "electricity.contract_is_fixed_price") is True and _value(facts, "electricity.first_annual_renewal_already_occurred") is False:
        if "electricity.supplier_direct_loss_proof_status" not in facts:
            return _ask(
                "electricity.supplier_direct_loss_proof_status",
                "¿La comercializadora ha aportado un cálculo o documentación que pruebe una pérdida económica directa causada por tu cancelación?",
                "choice",
                [
                    {"value": "none_or_not_provided", "label": "No ha aportado ninguna justificación"},
                    {"value": "provided_needs_validation", "label": "Sí, ha aportado un cálculo o documento"},
                ],
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
        "18.5-18.7, 51.3",
        {"supplier_switch": True},
        {
            "express_consent_required": True,
            "durable_proof_retention_years": 5,
            "restore_previous_supplier_if_no_consent_or_wrong_cups": True,
            "no_payment_for_unsolicited_supply": True,
        },
        "El comercializador entrante debe asegurar consentimiento expreso y conservarlo en soporte duradero al menos cinco años. Un cambio sin consentimiento o por CUPS incorrecto debe restituirse al comercializador saliente y contrato previo; no puede reclamarse pago por suministro no solicitado.",
    )
    rules["ELEC_EARLY_TERMINATION_CURRENT"] = svc._ensure_rule(
        db,
        "ELEC_EARLY_TERMINATION_CURRENT",
        1,
        date(2026, 6, 12),
        "RD88_2026",
        "28.3; DT 8.ª; DF 9.ª.4",
        {"natural_person": True, "tariff": "2.0TD"},
        {
            "general_penalty": False,
            "sole_exception": "fixed_price_before_first_annual_renewal",
            "supplier_must_prove_direct_loss": True,
            "statutory_cap_requires_estimation_method": True,
        },
        "Desde el 12/06/2026, una persona física en 2.0TD puede rescindir sin penalización salvo contrato a precio fijo antes de la primera prórroga anual. Incluso en la excepción, el comercializador debe acreditar pérdida económica directa y respetar el límite legal.",
    )
    return rules


def _create_case(db: Session, message: str):
    case = _ORIGINAL_CREATE(db, message)
    titles = {
        "E03": "Cambio de comercializadora sin consentimiento",
        "E05": "Penalización o permanencia por cancelar el suministro",
    }
    if case.family in titles:
        case.title = titles[case.family]
        db.commit()
        db.refresh(case)
    return case


def _prepare_claim_package(db: Session, case) -> dict[str, Any]:
    if case.family not in {"E03", "E05"}:
        return _ORIGINAL_PREPARE(db, case)

    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing an automated action")

    facts = svc.latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )

    if case.family == "E03":
        result = evaluate_e03(facts)
        if result.next_action != "PREPARE_UNAUTHORIZED_SWITCH_RESTORATION":
            raise ValueError("Current E03 action requires more information or human review")
        amount = round(float(decision.claimable_amount or 0.0), 2)
        old = _value(facts, "electricity.previous_supplier", "comercializadora anterior")
        new = _value(facts, "electricity.incoming_supplier", "comercializadora entrante")
        remedies = list(result.remedies)
        legal_basis = [{
            "rule_id": "ELEC_SWITCH_EXPRESS_CONSENT",
            "article": "18.5-18.7 y 51.3",
            "source": "RD 88/2026",
        }]
        claim_type = "E03_UNAUTHORIZED_SWITCH_RESTORATION"
        text = (
            f"Impugno el cambio de suministro desde {old} a {new} por falta de consentimiento expreso o por error de identificación del punto, según los hechos del expediente. "
            "Solicito la restitución al comercializador saliente y al contrato previo conforme a los artículos 18 y 51.3 del RD 88/2026, así como el cese de cargos por suministro no solicitado."
        )
        if amount > 0:
            text += f" Solicito además la devolución de {amount:.2f} € ya pagados por el suministro no solicitado identificado en el expediente."
    else:
        result = evaluate_e05(facts)
        amount = round(float(decision.claimable_amount or 0.0), 2)
        legal_basis = [{
            "rule_id": "ELEC_EARLY_TERMINATION_CURRENT",
            "article": "28.3",
            "source": "RD 88/2026",
        }]
        if result.next_action == "REQUEST_PENALTY_JUSTIFICATION":
            claim_type = "E05_REQUEST_PENALTY_JUSTIFICATION"
            remedies = ["REQUEST_DIRECT_LOSS_PROOF", "REQUEST_PENALTY_CALCULATION"]
            amount = 0.0
            text = (
                "Solicito la justificación documental de la penalización por rescisión anticipada, incluyendo la acreditación de la pérdida económica directa y el cálculo aplicado. "
                "El artículo 28.3 del RD 88/2026 atribuye al comercializador la carga de probar dicha pérdida y limita la penalización en los supuestos en que puede proceder."
            )
        elif result.next_action in {"PREPARE_INVALID_TERMINATION_PENALTY_CLAIM", "PREPARE_UNPROVEN_TERMINATION_PENALTY_CLAIM"}:
            if amount <= 0:
                raise ValueError("No verified penalty amount is available for a monetary refund action")
            claim_type = "E05_TERMINATION_PENALTY_CHALLENGE"
            remedies = ["CANCEL_PENALTY", "REFUND_PENALTY_IF_PAID"]
            text = (
                f"Impugno la penalización de {amount:.2f} € aplicada por la rescisión del contrato. "
                "Conforme al artículo 28.3 del RD 88/2026, una persona física en 2.0TD puede rescindir sin penalización salvo la excepción legal de precio fijo antes de la primera prórroga anual; cuando la excepción pueda operar, la carga de acreditar la pérdida económica directa recae en el comercializador."
            )
        else:
            raise ValueError("Current E05 action requires more information or human review")

    payload = {
        "claim_type": claim_type,
        "remedies": remedies,
        "amount": amount,
        "economic_value": decision.economic_value,
        "currency": "EUR",
        "legal_basis": legal_basis,
        "text": text,
    }
    action = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        status="READY",
        payload_json=payload,
    )
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
        "CUPS_CORRECT_ASSERTED": "company.asserts_correct_cups",
        "EARLY_TERMINATION_EXCEPTION_ASSERTED": "company.asserts_fixed_price_pre_first_renewal",
    }
    for argument in result.get("arguments", []):
        key = mapping.get(argument)
        if key:
            svc.upsert_fact(
                db, case, key, True,
                state="asserted", user_confirmed=False, created_by="company",
            )
    return result


def install_electricity_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS.update({"E03": evaluate_e03, "E05": evaluate_e05})
    svc.FAMILY_RULES.update({
        "E03": ["ELEC_SWITCH_EXPRESS_CONSENT"],
        "E05": ["ELEC_EARLY_TERMINATION_CURRENT"],
    })
    svc.next_question = _next_question
    svc.seed_legal = _seed_legal
    svc.create_case = _create_case
    svc.prepare_claim_package = _prepare_claim_package
    svc.analyze_company_response = _analyze_company_response
    _INSTALLED = True
