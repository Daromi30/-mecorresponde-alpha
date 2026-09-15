from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.c02 import evaluate_c02
from .engine.c03 import evaluate_c03
from .engine.common import FactValue
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


def _c02_question(facts: dict[str, FactValue]) -> dict:
    common = [
        ("purchase.buyer_is_consumer", "¿Compraste el producto como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Lo compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.product_name", "¿Qué producto es?", "text"),
        ("purchase.delivery_date", "¿Qué día te entregaron originalmente el producto?", "date"),
        ("purchase.price", "¿Cuánto pagaste por el producto?", "money"),
        ("purchase.conformity_attempts", "¿Cuántos intentos de reparación o sustitución ha hecho ya el vendedor?", "number"),
    ]
    for key, question, input_type in common:
        if key not in facts:
            return _ask(key, question, input_type)

    try:
        attempts = int(_value(facts, "purchase.conformity_attempts", 0) or 0)
    except (TypeError, ValueError):
        attempts = 0
    if attempts < 1:
        return {"done": True, "question": None, "field": None}

    if "purchase.lack_after_conformity_attempt" not in facts:
        return _ask(
            "purchase.lack_after_conformity_attempt",
            "Después del intento de reparación o sustitución, ¿el producto sigue teniendo una falta de conformidad o ha aparecido otra?",
            "boolean",
        )

    if _value(facts, "purchase.lack_after_conformity_attempt") is False:
        if "purchase.repair_still_pending" not in facts:
            return _ask("purchase.repair_still_pending", "¿La reparación sigue todavía pendiente?", "boolean")
        if _value(facts, "purchase.repair_still_pending") is True and "purchase.repair_started_date" not in facts:
            return _ask("purchase.repair_started_date", "¿Desde qué fecha tiene el vendedor el producto para repararlo?", "date")

    if "purchase.seller_declared_will_not_conform" not in facts:
        return _ask(
            "purchase.seller_declared_will_not_conform",
            "¿El vendedor te ha dicho claramente que no va a reparar, sustituir o poner el producto en conformidad?",
            "boolean",
        )

    qualifies = (
        _value(facts, "purchase.lack_after_conformity_attempt") is True
        or _value(facts, "purchase.seller_declared_will_not_conform") is True
    )
    if not qualifies:
        return {"done": True, "question": None, "field": None}

    if "purchase.defect_description" not in facts:
        return _ask("purchase.defect_description", "Describe brevemente qué problema sigue teniendo ahora el producto.", "text")
    if "purchase.same_origin_after_repair" not in facts:
        return _ask(
            "purchase.same_origin_after_repair",
            "¿El defecto que ha reaparecido parece ser del mismo origen que el que motivó la reparación?",
            "boolean",
        )
    if _value(facts, "purchase.same_origin_after_repair") is True and "purchase.repair_return_date" not in facts:
        return _ask("purchase.repair_return_date", "¿Qué día te devolvieron el producto tras la reparación?", "date")
    if "purchase.preferred_secondary_remedy" not in facts:
        return _ask(
            "purchase.preferred_secondary_remedy",
            "Si legalmente procede, ¿prefieres pedir la resolución de la compra o una reducción proporcional del precio?",
            "choice",
            [
                {"value": "termination", "label": "Resolver la compra y recuperar el precio"},
                {"value": "price_reduction", "label": "Pedir una reducción proporcional del precio"},
            ],
        )
    if _value(facts, "purchase.preferred_secondary_remedy") == "termination" and "purchase.defect_material" not in facts:
        return _ask(
            "purchase.defect_material",
            "¿El problema afecta de forma importante al uso, valor o características por las que compraste el producto?",
            "boolean",
        )
    return {"done": True, "question": None, "field": None}


def _c03_question(facts: dict[str, FactValue]) -> dict:
    order = [
        ("purchase.buyer_is_consumer", "¿Compraste el producto como particular, no para una actividad profesional o empresa?", "boolean"),
        ("purchase.seller_is_business", "¿Lo compraste a una tienda, empresa o vendedor profesional?", "boolean"),
        ("purchase.product_name", "¿Qué producto compraste?", "text"),
        ("purchase.delivery_date", "¿Qué día lo recibiste?", "date"),
        ("purchase.price", "¿Cuánto pagaste por el producto?", "money"),
        ("purchase.contract_description", "¿Qué producto, modelo, cantidad o accesorios figuraban en la compra o anuncio?", "text"),
        ("purchase.received_description", "¿Qué recibiste realmente y qué falta o qué es distinto?", "text"),
        ("purchase.mismatch_confirmed", "¿Confirmas que lo recibido no coincide con lo contratado en producto, modelo, cantidad, calidad o accesorios?", "boolean"),
        ("purchase.mismatch_material", "¿La diferencia afecta de forma importante al uso, cantidad, características o valor de la compra?", "boolean"),
        ("purchase.seller_denied_conformity", "¿El vendedor ya se ha negado a corregirlo, sustituirlo o completar lo que falta?", "boolean"),
    ]
    for key, question, input_type in order:
        if key not in facts:
            return _ask(key, question, input_type)
    return {"done": True, "question": None, "field": None}


def _next_question(facts: dict[str, FactValue], family: str | None) -> dict:
    if family == "C02":
        return _c02_question(facts)
    if family == "C03":
        return _c03_question(facts)
    return _ORIGINAL_NEXT_QUESTION(facts, family)


def _seed_legal(db: Session):
    rules = _ORIGINAL_SEED(db)
    rules["GOODS_POST_CONFORMITY_ATTEMPT"] = svc._ensure_rule(
        db,
        "GOODS_POST_CONFORMITY_ATTEMPT",
        1,
        date(2022, 1, 1),
        "TRLGDCU",
        "118, 119, 119 ter, 122",
        {"consumer_purchase": True, "prior_conformity_attempt": True},
        {
            "reasonable_time_not_fixed_days": True,
            "secondary_remedies_after_failed_attempt": True,
            "termination_excludes_minor_lack": True,
            "same_origin_post_repair_presumption_years": 1,
        },
        "La reparación o sustitución debe ser gratuita, realizarse en plazo razonable y sin mayores inconvenientes. Una falta tras el intento o una negativa clara del empresario puede abrir reducción del precio o resolución; la resolución no procede por una falta de escasa importancia y la repetición del mismo origen durante el año posterior a la puesta en conformidad tiene la presunción del artículo 122.3.",
    )
    rules["GOODS_CONTRACT_DESCRIPTION"] = svc._ensure_rule(
        db,
        "GOODS_CONTRACT_DESCRIPTION",
        1,
        date(2022, 1, 1),
        "TRLGDCU",
        "115 bis, 117-119 ter",
        {"consumer_purchase": True, "goods_mismatch_contract": True},
        {
            "description_type_quantity_quality_must_match": True,
            "accessories_and_instructions_must_match_contract": True,
            "conformity_remedies_apply": True,
        },
        "Los bienes deben ajustarse a la descripción, tipo, cantidad y calidad pactadas y entregarse con los accesorios e instrucciones contractualmente exigibles. La falta de conformidad activa los remedios de los artículos 117 a 119 ter.",
    )
    return rules


def _create_case(db: Session, message: str):
    case = _ORIGINAL_CREATE(db, message)
    titles = {
        "C02": "Reparación fallida, repetida o demorada",
        "C03": "Producto equivocado, incompleto o distinto de lo contratado",
    }
    if case.family in titles:
        case.title = titles[case.family]
        db.commit()
        db.refresh(case)
    return case


def _prepare_claim_package(db: Session, case) -> dict[str, Any]:
    if case.family not in {"C02", "C03"}:
        return _ORIGINAL_PREPARE(db, case)

    decision = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).first()
    if not decision:
        raise ValueError("Diagnose the case before preparing a claim")
    if decision.viability not in {"HIGH", "MEDIUM"}:
        raise ValueError("Current diagnosis does not support preparing a claim")

    facts = svc.latest_facts(db, case.id)
    facts.setdefault(
        "system.analysis_date",
        FactValue(value=date.today().isoformat(), state="confirmed", user_confirmed=False),
    )
    product = facts.get("purchase.product_name").value if facts.get("purchase.product_name") else "producto"

    if case.family == "C02":
        result = evaluate_c02(facts)
        legal_basis = [{
            "rule_id": "GOODS_POST_CONFORMITY_ATTEMPT",
            "article": "118, 119, 119 ter, 122",
            "source": "TRLGDCU",
        }]
        remedies = list(result.remedies)
        if result.next_action == "PREPARE_C02_TERMINATION":
            amount = round(float(decision.claimable_amount or 0.0), 2)
            if amount <= 0:
                raise ValueError("Termination is not sufficiently supported to calculate a full-price refund")
            claim_type = "C02_TERMINATION_AFTER_FAILED_CONFORMITY"
            text = (
                f"Tras el intento previo de puesta en conformidad del {product}, persiste o ha aparecido una nueva falta de conformidad. "
                f"Comunico mi voluntad de resolver el contrato y solicito la restitución de {amount:.2f} €, con fundamento en los artículos 119 y 119 ter del TRLGDCU. "
                "La resolución queda sujeta a que la falta no sea de escasa importancia."
            )
        elif result.next_action == "PREPARE_C02_PRICE_REDUCTION":
            amount = 0.0
            claim_type = "C02_PRICE_REDUCTION_AFTER_FAILED_CONFORMITY"
            text = (
                f"Tras el intento previo de puesta en conformidad del {product}, persiste o ha aparecido una nueva falta de conformidad. "
                "Solicito una reducción proporcionada del precio conforme a los artículos 119 y 119 bis del TRLGDCU. "
                "El importe debe fijarse de forma proporcional a la diferencia de valor y no se inventa automáticamente en esta alpha."
            )
        else:
            raise ValueError("Choose the secondary remedy before preparing the C02 claim")
    else:
        result = evaluate_c03(facts)
        legal_basis = [{
            "rule_id": "GOODS_CONTRACT_DESCRIPTION",
            "article": "115 bis, 117-119 ter",
            "source": "TRLGDCU",
        }]
        remedies = list(result.remedies)
        amount = 0.0
        if result.next_action == "PREPARE_C03_CONFORMITY_CLAIM":
            claim_type = "C03_CONTRACT_MISMATCH_CONFORMITY"
            text = (
                f"El {product} recibido no se ajusta a lo contratado en descripción, tipo, cantidad, calidad o accesorios. "
                "Solicito su puesta en conformidad sin coste mediante sustitución, entrega de lo faltante o la medida correctora que corresponda, conforme a los artículos 115 bis, 117 y 118 del TRLGDCU."
            )
        elif result.next_action == "PREPARE_C03_ESCALATED_REMEDY":
            claim_type = "C03_CONTRACT_MISMATCH_ESCALATED"
            text = (
                f"El {product} recibido no se ajusta a lo contratado y el vendedor ya ha rechazado ponerlo en conformidad. "
                "Solicito la medida correctora secundaria que corresponda —reducción proporcionada del precio o resolución si la falta no es de escasa importancia— conforme a los artículos 119 a 119 ter del TRLGDCU."
            )
        else:
            raise ValueError("Current C03 action does not require sending a claim yet")

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
        "GOODS_MATCH_CONTRACT_ASSERTED": "company.asserts_goods_match_contract",
    }
    for argument in result.get("arguments", []):
        key = mapping.get(argument)
        if key:
            svc.upsert_fact(
                db, case, key, True,
                state="asserted", user_confirmed=False, created_by="company",
            )
    return result


def install_purchase_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS.update({"C02": evaluate_c02, "C03": evaluate_c03})
    svc.FAMILY_RULES.update({
        "C02": ["GOODS_POST_CONFORMITY_ATTEMPT"],
        "C03": ["GOODS_CONTRACT_DESCRIPTION"],
    })
    svc.next_question = _next_question
    svc.seed_legal = _seed_legal
    svc.create_case = _create_case
    svc.prepare_claim_package = _prepare_claim_package
    svc.analyze_company_response = _analyze_company_response
    _INSTALLED = True
