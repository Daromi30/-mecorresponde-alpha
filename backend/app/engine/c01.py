from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw, verified

CURRENT_REGIME_START = date(2022, 1, 1)
TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"


def _parse_date(v):
    if isinstance(v, str):
        return date.fromisoformat(v)
    return v


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


def evaluate_c01(facts: dict[str, FactValue]) -> EngineResult:
    sources = [{"title": "TRLGDCU, arts. 117-121 y 124-125", "url": TRLGDCU_URL}]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []
    failed: list[str] = []

    buyer_consumer = raw(facts, "purchase.buyer_is_consumer")
    seller_business = raw(facts, "purchase.seller_is_business")
    if buyer_consumer is None:
        missing.append("purchase.buyer_is_consumer")
    if seller_business is None:
        missing.append("purchase.seller_is_business")
    if buyer_consumer is False or seller_business is False:
        return EngineResult(
            viability="OUT_OF_SCOPE", scope_status="UNSUPPORTED", claimable_amount=None,
            economic_value=raw(facts, "purchase.price"), worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="El régimen automatizado C01 está limitado a compras de una persona consumidora frente a un vendedor profesional.",
            counterarguments=[], missing_facts=[], next_action="REDIRECT_NON_CONSUMER_PURCHASE",
            rule_result="NOT_APPLICABLE", failed_conditions=["consumer_or_business_scope_failed"], calculation=None,
            sources=sources, remedies=[], burden_of_proof=[],
        )

    second_hand = raw(facts, "purchase.second_hand")
    if second_hand is None:
        missing.append("purchase.second_hand")
    elif second_hand is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LIMITED_SCOPE", claimable_amount=None,
            economic_value=raw(facts, "purchase.price"), worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Los bienes de segunda mano pueden tener un plazo de responsabilidad pactado distinto, nunca inferior a un año. Esta alpha todavía no automatiza esa comprobación contractual.",
            counterarguments=[], missing_facts=[], next_action="HUMAN_REVIEW_SECOND_HAND",
            rule_result="MANUAL_REVIEW", failed_conditions=[], calculation=None, sources=sources,
            remedies=[], burden_of_proof=[],
        )

    product = raw(facts, "purchase.product_name")
    if not product:
        missing.append("purchase.product_name")
    delivery = raw(facts, "purchase.delivery_date")
    manifested = raw(facts, "purchase.defect_manifested_date")
    if not delivery:
        missing.append("purchase.delivery_date")
    else:
        delivery = _parse_date(delivery)
    if not manifested:
        missing.append("purchase.defect_manifested_date")
    else:
        manifested = _parse_date(manifested)
    defect = raw(facts, "purchase.defect_description")
    if not defect:
        missing.append("purchase.defect_description")

    price = raw(facts, "purchase.price")
    economic_value = round(float(price), 2) if price is not None else None

    if delivery and delivery < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW", claimable_amount=None,
            economic_value=economic_value, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La entrega es anterior al régimen de conformidad automatizado vigente desde el 1/1/2022; hay que aplicar la redacción histórica correspondiente.",
            counterarguments=[], missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["delivery_before_2022-01-01"], calculation=None,
            sources=sources, remedies=[], burden_of_proof=[],
        )

    if delivery and manifested and manifested < delivery:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            economic_value=economic_value, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="La fecha indicada para la aparición del defecto es anterior a la entrega. Hay que corregir la cronología antes de aplicar las reglas de garantía.",
            counterarguments=[], missing_facts=["purchase.defect_manifested_date"], next_action="CORRECT_TIMELINE",
            rule_result="PENDING", failed_conditions=["manifestation_before_delivery"], calculation=None,
            sources=sources, remedies=[], burden_of_proof=[],
        )

    repair_attempts = raw(facts, "purchase.repair_attempts", 0) or 0
    defect_after_repair = raw(facts, "purchase.defect_after_repair", False)
    if int(repair_attempts) > 0 or defect_after_repair is True:
        return EngineResult(
            viability="RECLASSIFY", scope_status="REDIRECT_C02", claimable_amount=None,
            economic_value=economic_value, worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="Ya existe al menos un intento de puesta en conformidad. El caso debe analizarse con C02, que evalúa reparación fallida, repetición del defecto y acceso a reducción del precio o resolución.",
            counterarguments=[], missing_facts=[], next_action="RECLASSIFY_C02",
            rule_result="NOT_APPLICABLE", failed_conditions=["prior_repair_attempt"], calculation=None,
            sources=sources, remedies=[], burden_of_proof=[],
        )

    if delivery and manifested:
        three_year_limit = _add_years(delivery, 3)
        two_year_presumption = _add_years(delivery, 2)
        if manifested > three_year_limit:
            return EngineResult(
                viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
                economic_value=economic_value, worth_pursuing="NO_PAID_MANAGEMENT",
                reasoning_summary="La falta de conformidad se manifestó después del plazo de tres años desde la entrega previsto para bienes nuevos en el artículo 120 del TRLGDCU. Este árbol de garantía legal no queda sustentado con los datos actuales.",
                counterarguments=[], missing_facts=[], next_action="EXPLAIN_OUTSIDE_MANIFESTATION_PERIOD",
                rule_result="FAILED", failed_conditions=["manifested_after_three_year_period"], calculation=None,
                sources=sources, remedies=[], burden_of_proof=[],
            )
        within_presumption = manifested <= two_year_presumption
    else:
        within_presumption = False

    accidental = raw(facts, "purchase.accidental_damage_or_misuse")
    if accidental is None:
        missing.append("purchase.accidental_damage_or_misuse")
    elif accidental is True:
        failed.append("known_accidental_damage_or_misuse")
        counterarguments.append({"type":"ACCIDENTAL_DAMAGE_OR_MISUSE","status":"confirmed","impact":"critical"})

    if raw(facts, "company.asserts_misuse", False):
        counterarguments.append({"type":"ACCIDENTAL_DAMAGE_OR_MISUSE","status":"open","impact":"critical","origin":"company_response"})
    if raw(facts, "company.asserts_outside_guarantee", False):
        counterarguments.append({"type":"SELLER_ASSERTS_OUTSIDE_GUARANTEE","status":"open","impact":"material","origin":"company_response"})
    if raw(facts, "company.redirects_to_manufacturer", False):
        counterarguments.append({"type":"SELLER_REDIRECTS_TO_MANUFACTURER","status":"open","impact":"minor","origin":"company_response"})

    burden: list[dict[str, Any]] = []
    if delivery and manifested and within_presumption:
        burden.append({
            "issue": "lack_of_conformity_existed_at_delivery",
            "on": "seller",
            "basis": "TRLGDCU_121",
            "note": "Presunción durante los dos años siguientes a la entrega, salvo incompatibilidad con la naturaleza del bien o de la falta de conformidad.",
        })
        counterarguments.append({"type":"PRESUMPTION_MAY_BE_INCOMPATIBLE_WITH_NATURE_OR_DEFECT","status":"potential","impact":"material"})
    elif delivery and manifested:
        burden.append({
            "issue": "lack_of_conformity_existed_at_delivery",
            "on": "consumer_needs_supporting_evidence",
            "basis": "TRLGDCU_120_121",
            "note": "La manifestación está dentro de los tres años pero fuera de la presunción de dos años.",
        })

    if failed:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            economic_value=economic_value, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Con los hechos confirmados, el defecto se atribuye a daño accidental o mal uso conocido, por lo que no queda sustentado como falta de conformidad imputable al vendedor en este árbol.",
            counterarguments=counterarguments, missing_facts=missing, next_action="EXPLAIN_NO_CONFORMITY_BASIS",
            rule_result="FAILED", failed_conditions=failed, calculation=None, sources=sources,
            remedies=[], burden_of_proof=burden,
        )

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            economic_value=economic_value, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para determinar si el defecto entra en la garantía legal y qué remedio corresponde.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)), next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING", failed_conditions=[], calculation=None, sources=sources,
            remedies=[], burden_of_proof=burden,
        )

    seller_denied = raw(facts, "purchase.seller_denied_conformity", False)
    severity = raw(facts, "purchase.defect_severity")
    remedies = ["REPAIR", "REPLACEMENT"]
    next_action = "PREPARE_CONFORMITY_CLAIM"
    if seller_denied:
        remedies.extend(["PRICE_REDUCTION"])
        if severity != "minor":
            remedies.append("TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT")
        next_action = "PREPARE_REJECTED_WARRANTY_CLAIM"
        counterarguments.append({"type":"SELLER_REFUSED_CONFORMITY","status":"confirmed","impact":"supports_secondary_remedies"})

    open_critical = any(c.get("impact") == "critical" and c.get("status") == "open" for c in counterarguments)
    viability = "HIGH" if within_presumption and not open_critical else "MEDIUM"

    if economic_value is None:
        worth = "NEEDS_INFORMATION"
    elif economic_value < 30:
        worth = "YES_IF_LOW_COST"
    else:
        worth = "YES"

    reasoning = (
        "La falta de conformidad se manifestó dentro del plazo de tres años desde la entrega. "
        + ("Además, está dentro de los dos primeros años, por lo que opera la presunción legal de que ya existía al entregarse el bien, salvo la excepción prevista por la naturaleza del bien o del defecto. " if within_presumption else "Al haberse manifestado después de los dos primeros años, la garantía legal puede seguir vigente, pero será especialmente importante acreditar que la falta de conformidad existía al entregarse el bien. ")
        + "Como regla inicial, el consumidor puede exigir reparación o sustitución sin coste, salvo imposibilidad o desproporción."
    )
    if seller_denied:
        reasoning += " La negativa del vendedor a poner el bien en conformidad puede abrir el acceso a reducción del precio o resolución en los términos del artículo 119; la resolución no procede si la falta es de escasa importancia."

    return EngineResult(
        viability=viability, scope_status="SUPPORTED", claimable_amount=0.0,
        economic_value=economic_value, worth_pursuing=worth, reasoning_summary=reasoning,
        counterarguments=counterarguments, missing_facts=[], next_action=next_action,
        rule_result="APPLIES", failed_conditions=[], calculation=None, sources=sources,
        remedies=remedies, burden_of_proof=burden,
    )
