from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as base
from .engine.c02 import evaluate_c02
from .engine.c03 import evaluate_c03
from .engine.common import FactValue
from .models import Action, Case, Decision


# Extend the existing stable service rather than creating a second independent
# implementation of the core. C02/C03 register into the same evaluator/rule
# pipeline, preserving one source of truth for case workflow and audit.
_base_seed_legal = base.seed_legal


def _seed_legal_v3(db: Session):
    rules = _base_seed_legal(db)
    rules["GOODS_POST_CONFORMITY_REMEDIES"] = base._ensure_rule(
        db,
        "GOODS_POST_CONFORMITY_REMEDIES",
        1,
        date(2022, 1, 1),
        "TRLGDCU",
        "118-119 ter, 122",
        {"consumer_purchase": True, "prior_conformity_attempt": True},
        {
            "secondary_remedies_on_statutory_triggers": ["price_reduction", "termination"],
            "termination_excludes_minor_lack": True,
            "same_origin_post_repair_presumption_years": 1,
        },
        "Tras un intento de puesta en conformidad, los supuestos del artículo 119 pueden abrir reducción del precio o resolución; la resolución no procede por falta de escasa importancia y el artículo 122 contiene una presunción específica durante un año para defectos del mismo origen.",
    )
    rules["GOODS_DESCRIPTION_CONFORMITY"] = base._ensure_rule(
        db,
        "GOODS_DESCRIPTION_CONFORMITY",
        1,
        date(2022, 1, 1),
        "TRLGDCU",
        "115 bis, 117-119 ter",
        {"consumer_purchase": True, "goods_do_not_match_contract": True},
        {
            "contractual_requirements": ["description", "type", "quantity", "quality", "accessories"],
            "initial_remedy": "put_in_conformity",
        },
        "Los bienes deben ajustarse a la descripción, tipo, cantidad y calidad pactadas y entregarse con los accesorios exigibles; la falta de conformidad activa las medidas correctoras del título.",
    )
    return rules


base.seed_legal = _seed_legal_v3
base.EVALUATORS.update({"C02": evaluate_c02, "C03": evaluate_c03})
base.FAMILY_RULES.update({
    "C02": ["GOODS_POST_CONFORMITY_REMEDIES"],
    "C03": ["GOODS_DESCRIPTION_CONFORMITY"],
})


def audit(*args, **kwargs):
    return base.audit(*args, **kwargs)


def create_human_review(*args, **kwargs):
    return base.create_human_review(*args, **kwargs)


def upsert_fact(*args, **kwargs):
    return base.upsert_fact(*args, **kwargs)


def confirm_document_fact(*args, **kwargs):
    return base.confirm_document_fact(*args, **kwargs)


def latest_facts(*args, **kwargs):
    return base.latest_facts(*args, **kwargs)


def get_next_question(*args, **kwargs):
    return base.get_next_question(*args, **kwargs)


def create_case(db: Session, message: str) -> Case:
    case = base.create_case(db, message)
    title = {
        "C02": "Reparación o sustitución fallida/repetida",
        "C03": "Producto equivocado, incompleto o distinto de lo contratado",
    }.get(case.family or "")
    if title:
        case.title = title
        db.commit()
        db.refresh(case)
    return case


def diagnose(db: Session, case: Case):
    return base.diagnose(db, case)


def analyze_company_response(db: Session, case: Case, text: str):
    result = base.analyze_company_response(db, case, text)
    if "GOODS_MATCH_CONTRACT_ASSERTED" in result.get("arguments", []):
        base.upsert_fact(
            db,
            case,
            "company.asserts_goods_match_contract",
            True,
            state="asserted",
            user_confirmed=False,
            created_by="company",
        )
        case.status = "RESPONSE_RECEIVED"
        base.audit(db, case.id, "C03_COMPANY_ARGUMENT_RECORDED", {"argument": "GOODS_MATCH_CONTRACT_ASSERTED"})
        db.commit()
    return result


def _prepare_new_purchase_claim(db: Session, case: Case) -> dict[str, Any]:
    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing a claim")

    facts = base.latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )
    amount = round(float(decision.claimable_amount or 0.0), 2)
    amount_status = "CALCULATED" if amount > 0 else "NON_MONETARY_OR_PENDING_CALCULATION"

    if case.family == "C02":
        result = evaluate_c02(facts)
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"
        legal_basis = [{
            "rule_id": "GOODS_POST_CONFORMITY_REMEDIES",
            "article": "118-119 ter, 122",
            "source": "TRLGDCU",
        }]
        if result.next_action == "PREPARE_C02_TERMINATION":
            if amount <= 0:
                raise ValueError("Termination is not yet supported by a verified non-minor defect and product value")
            remedies = ["TERMINATION", "REFUND_AFTER_RETURN_OR_PROOF"]
            claim_type = "C02_TERMINATION_AFTER_FAILED_CONFORMITY"
            text = (
                f"Comunico mi voluntad de resolver la compra del {product} tras el intento de puesta en conformidad y solicito la restitución del precio de {amount:.2f} €. "
                "La solicitud se formula conforme a los artículos 119 y 119 ter del TRLGDCU. La ejecución del reembolso se coordinará con la restitución del bien en los términos legales aplicables."
            )
        elif result.next_action == "PREPARE_C02_PRICE_REDUCTION":
            remedies = ["PRICE_REDUCTION"]
            claim_type = "C02_PROPORTIONAL_PRICE_REDUCTION"
            amount = 0.0
            amount_status = "REQUIRES_PROPORTIONAL_VALUATION"
            text = (
                f"Tras el intento de puesta en conformidad del {product}, solicito una reducción proporcional del precio conforme a los artículos 119 y 119 bis del TRLGDCU. "
                "El importe de la reducción debe corresponder a la diferencia de valor legalmente relevante y no se fija de forma automática sin una base de valoración suficiente."
            )
        else:
            raise ValueError("Current C02 action requires more facts, review or a remedy choice before preparing a claim")
    elif case.family == "C03":
        result = evaluate_c03(facts)
        product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"
        remedies = list(result.remedies)
        legal_basis = [{
            "rule_id": "GOODS_DESCRIPTION_CONFORMITY",
            "article": "115 bis, 117-119",
            "source": "TRLGDCU",
        }]
        amount = 0.0
        amount_status = "NON_MONETARY_INITIAL_REMEDY"
        if result.next_action == "PREPARE_C03_CONFORMITY_CLAIM":
            claim_type = "C03_PUT_GOODS_IN_CONFORMITY"
            text = (
                f"Solicito que el {product} sea puesto en conformidad sin coste, corrigiendo la diferencia entre lo contratado y lo recibido mediante la medida que legalmente corresponda. "
                "Los artículos 115 bis, 117 y 118 del TRLGDCU exigen, entre otros extremos, ajuste a la descripción, tipo, cantidad, calidad y accesorios pactados."
            )
        elif result.next_action == "PREPARE_C03_ESCALATED_REMEDY":
            claim_type = "C03_CONFORMITY_REFUSAL_ESCALATION"
            text = (
                f"El {product} recibido no coincide con lo contratado y el vendedor se ha negado a ponerlo en conformidad. Solicito la medida correctora que corresponda y dejo expresamente planteados los remedios posteriores previstos en el artículo 119 del TRLGDCU, incluida reducción del precio o resolución cuando concurran sus requisitos."
            )
        else:
            raise ValueError("Current C03 action does not require preparing a claim")
    else:
        raise ValueError("Unsupported family")

    payload = {
        "claim_type": claim_type,
        "remedies": remedies,
        "amount": amount,
        "amount_status": amount_status,
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
    base.audit(db, case.id, "CLAIM_PACKAGE_PREPARED", {
        "action_id": action.id,
        "amount": amount,
        "amount_status": amount_status,
        "economic_value": decision.economic_value,
        "family": case.family,
    })
    db.commit()
    db.refresh(action)
    return {"action_id": action.id, **payload}


def prepare_claim_package(db: Session, case: Case) -> dict[str, Any]:
    if case.family in {"C02", "C03"}:
        return _prepare_new_purchase_claim(db, case)
    return base.prepare_claim_package(db, case)
