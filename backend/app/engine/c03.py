from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"
CURRENT_REGIME_START = date(2022, 1, 1)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _worth(value: float | None) -> str:
    if value is None:
        return "NEEDS_INFORMATION"
    return "YES_IF_LOW_COST" if value < 30 else "YES"


def evaluate_c03(facts: dict[str, FactValue]) -> EngineResult:
    """C03 — wrong, incomplete or materially not-as-described goods."""
    sources = [
        {"title": "TRLGDCU, arts. 115 bis y 117-119 ter", "url": TRLGDCU_URL}
    ]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    consumer = raw(facts, "purchase.buyer_is_consumer")
    business = raw(facts, "purchase.seller_is_business")
    if consumer is None:
        missing.append("purchase.buyer_is_consumer")
    if business is None:
        missing.append("purchase.seller_is_business")
    if consumer is False or business is False:
        return EngineResult(
            viability="OUT_OF_SCOPE", scope_status="UNSUPPORTED",
            claimable_amount=None, economic_value=raw(facts, "purchase.price"),
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="C03 automatiza compras de una persona consumidora frente a un vendedor profesional.",
            counterarguments=[], missing_facts=[], next_action="REDIRECT_NON_CONSUMER_PURCHASE",
            rule_result="NOT_APPLICABLE", failed_conditions=["consumer_or_business_scope_failed"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    product = raw(facts, "purchase.product_name")
    delivery = _parse_date(raw(facts, "purchase.delivery_date"))
    price_raw = raw(facts, "purchase.price")
    price = round(float(price_raw), 2) if price_raw is not None else None
    mismatch = raw(facts, "purchase.mismatch_confirmed")
    ordered = raw(facts, "purchase.contract_description")
    received = raw(facts, "purchase.received_description")
    denied = raw(facts, "purchase.seller_denied_conformity")
    material = raw(facts, "purchase.mismatch_material")

    if not product:
        missing.append("purchase.product_name")
    if delivery is None:
        missing.append("purchase.delivery_date")
    if price is None:
        missing.append("purchase.price")
    if mismatch is None:
        missing.append("purchase.mismatch_confirmed")
    if not ordered:
        missing.append("purchase.contract_description")
    if not received:
        missing.append("purchase.received_description")
    if denied is None:
        missing.append("purchase.seller_denied_conformity")
    if material is None:
        missing.append("purchase.mismatch_material")

    if delivery and delivery < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW",
            claimable_amount=None, economic_value=price, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La entrega es anterior al régimen de conformidad automatizado vigente desde el 1/1/2022; debe aplicarse la redacción histórica correspondiente.",
            counterarguments=[], missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["delivery_before_2022-01-01"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if raw(facts, "company.asserts_goods_match_contract", False):
        counterarguments.append({
            "type": "SELLER_ASSERTS_GOODS_MATCH_CONTRACT", "status": "open",
            "impact": "material", "origin": "company_response",
        })

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=price, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para comparar lo contratado con lo recibido y determinar el remedio adecuado.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if mismatch is False:
        return EngineResult(
            viability="LOW", scope_status="REDIRECT_OTHER_PURCHASE_ISSUE",
            claimable_amount=0.0, economic_value=price, worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="Con los hechos confirmados, lo recibido coincide con lo contratado. C03 no es la familia correcta para el problema descrito.",
            counterarguments=counterarguments, missing_facts=[], next_action="RECLASSIFY_PURCHASE_ISSUE",
            rule_result="FAILED", failed_conditions=["no_contract_mismatch"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    remedies = ["REPLACEMENT_OR_COMPLETION", "REPAIR_IF_APPLICABLE"]
    next_action = "PREPARE_C03_CONFORMITY_CLAIM"
    claimable = 0.0

    if denied is True:
        remedies.extend(["PRICE_REDUCTION", "TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT"])
        next_action = "PREPARE_C03_ESCALATED_REMEDY"
        counterarguments.append({
            "type": "SELLER_REFUSED_CONFORMITY", "status": "confirmed",
            "impact": "supports_secondary_remedies", "origin": "user_fact",
        })

    if material is False:
        counterarguments.append({
            "type": "MINOR_MISMATCH_MAY_BAR_TERMINATION", "status": "potential",
            "impact": "material", "origin": "known_rule",
        })

    open_material = any(
        c.get("status") == "open" and c.get("impact") in {"material", "critical"}
        for c in counterarguments
    )
    viability = "MEDIUM" if open_material else "HIGH"

    reasoning = (
        "Los bienes deben ajustarse a la descripción, tipo, cantidad y calidad pactadas y entregarse con los accesorios e instrucciones exigibles. "
        "La diferencia confirmada entre lo contratado y lo recibido constituye una posible falta de conformidad. Como regla inicial procede poner el bien en conformidad sin coste; si el vendedor se niega o concurre otro supuesto del artículo 119, pueden abrirse reducción del precio o resolución, esta última salvo faltas de escasa importancia."
    )

    return EngineResult(
        viability=viability, scope_status="SUPPORTED", claimable_amount=claimable,
        economic_value=price, worth_pursuing=_worth(price), reasoning_summary=reasoning,
        counterarguments=counterarguments, missing_facts=[], next_action=next_action,
        rule_result="APPLIES", failed_conditions=[],
        calculation={
            "type": "c03_contract_mismatch", "price": price,
            "contract_description": ordered, "received_description": received,
            "seller_denied": denied,
        },
        sources=sources, remedies=remedies,
        burden_of_proof=[{
            "issue": "contractual_description_quantity_quality_accessories",
            "on": "case_evidence",
            "basis": "TRLGDCU_115_BIS",
            "note": "Debe conservarse la prueba de lo ofertado/contratado y de lo efectivamente recibido.",
        }],
    )
