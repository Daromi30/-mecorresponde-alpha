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


def evaluate_c02(facts: dict[str, FactValue]) -> EngineResult:
    """C02 — failed/repeated/slow statutory conformity attempt.

    The engine automates clear Article 119 triggers. It deliberately does not
    turn a number of repair days into a universal legal deadline: whether a
    pending repair is taking a "reasonable time" depends on the circumstances
    and is routed to human review when that is the decisive question.
    """
    sources = [
        {"title": "TRLGDCU, arts. 118, 119, 119 ter y 122", "url": TRLGDCU_URL}
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
            reasoning_summary="C02 automatiza compras de una persona consumidora frente a un vendedor profesional.",
            counterarguments=[], missing_facts=[], next_action="REDIRECT_NON_CONSUMER_PURCHASE",
            rule_result="NOT_APPLICABLE", failed_conditions=["consumer_or_business_scope_failed"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    product = raw(facts, "purchase.product_name")
    delivery = _parse_date(raw(facts, "purchase.delivery_date"))
    price_raw = raw(facts, "purchase.price")
    price = round(float(price_raw), 2) if price_raw is not None else None
    attempts = raw(facts, "purchase.conformity_attempts")
    lack_after = raw(facts, "purchase.lack_after_conformity_attempt")
    pending = raw(facts, "purchase.repair_still_pending")
    refusal = raw(facts, "purchase.seller_declared_will_not_conform")

    if not product:
        missing.append("purchase.product_name")
    if delivery is None:
        missing.append("purchase.delivery_date")
    if price is None:
        missing.append("purchase.price")
    if attempts is None:
        missing.append("purchase.conformity_attempts")

    if delivery and delivery < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW",
            claimable_amount=None, economic_value=price, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La entrega es anterior al régimen automatizado vigente desde el 1/1/2022. Debe aplicarse la redacción histórica correspondiente.",
            counterarguments=[], missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["delivery_before_2022-01-01"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    if attempts is not None and int(attempts) < 1:
        return EngineResult(
            viability="RECLASSIFY", scope_status="REDIRECT_C01",
            claimable_amount=0.0, economic_value=price, worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="No consta todavía un intento de puesta en conformidad. El caso debe analizarse primero como C01.",
            counterarguments=[], missing_facts=[], next_action="RECLASSIFY_C01",
            rule_result="NOT_APPLICABLE", failed_conditions=["no_prior_conformity_attempt"],
            calculation=None, sources=sources, remedies=["REPAIR", "REPLACEMENT"], burden_of_proof=[],
        )

    if attempts is not None and int(attempts) >= 1:
        if lack_after is None:
            missing.append("purchase.lack_after_conformity_attempt")
        if lack_after is False and pending is None:
            missing.append("purchase.repair_still_pending")
        if refusal is None:
            missing.append("purchase.seller_declared_will_not_conform")

    if raw(facts, "company.asserts_misuse", False):
        counterarguments.append({
            "type": "MISUSE_OR_ACCIDENTAL_DAMAGE", "status": "open",
            "impact": "critical", "origin": "company_response",
        })
    if raw(facts, "company.asserts_outside_guarantee", False):
        counterarguments.append({
            "type": "SELLER_ASSERTS_OUTSIDE_GUARANTEE", "status": "open",
            "impact": "material", "origin": "company_response",
        })

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED",
            claimable_amount=None, economic_value=price, worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para saber si el intento de reparación ya abre los remedios secundarios del artículo 119 o si la reparación sigue en curso.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT", rule_result="PENDING", failed_conditions=[],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    # A repair that is still pending may or may not have exceeded a reasonable
    # time. The alpha never invents a fixed number of days for Article 118.4.b.
    if lack_after is False and pending is True and refusal is not True:
        started = _parse_date(raw(facts, "purchase.repair_started_date"))
        context = []
        if started:
            context.append(f"La reparación consta iniciada el {started.isoformat()}.")
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LIMITED_SCOPE",
            claimable_amount=None, economic_value=price, worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(" ".join(context) + " El artículo 118 exige un plazo razonable y ausencia de mayores inconvenientes, pero no establece un número universal de días. La razonabilidad depende de la naturaleza del bien y de las circunstancias, por lo que este supuesto se revisa manualmente.").strip(),
            counterarguments=counterarguments, missing_facts=[],
            next_action="HUMAN_REVIEW_REPAIR_DELAY", rule_result="MANUAL_REVIEW",
            failed_conditions=[], calculation=None, sources=sources,
            remedies=["REPAIR", "REPLACEMENT", "PRICE_REDUCTION", "TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT"],
            burden_of_proof=[],
        )

    if lack_after is False and pending is False and refusal is not True:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            economic_value=price, worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Con los hechos actuales, la puesta en conformidad terminó y no consta una nueva falta de conformidad ni una negativa del vendedor. C02 no abre ahora un remedio adicional.",
            counterarguments=counterarguments, missing_facts=[], next_action="MONITOR_CONFORMITY",
            rule_result="FAILED", failed_conditions=["no_post_attempt_lack_or_refusal"],
            calculation=None, sources=sources, remedies=[], burden_of_proof=[],
        )

    trigger = "seller_refusal" if refusal is True and lack_after is not True else "lack_after_attempt"
    same_origin = raw(facts, "purchase.same_origin_after_repair")
    repair_return = _parse_date(raw(facts, "purchase.repair_return_date"))
    if lack_after is True and same_origin is None:
        same_origin = False

    burden: list[dict[str, Any]] = []
    if lack_after is True and same_origin is True and repair_return is not None:
        analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()
        try:
            one_year_later = repair_return.replace(year=repair_return.year + 1)
        except ValueError:
            one_year_later = repair_return.replace(month=2, day=28, year=repair_return.year + 1)
        if analysis_date <= one_year_later:
            burden.append({
                "issue": "same_origin_post_repair_defect",
                "on": "seller",
                "basis": "TRLGDCU_122_3",
                "note": "Durante el año posterior a la entrega del bien ya conforme se presume la misma falta cuando se reproducen defectos del mismo origen.",
            })

    material = raw(facts, "purchase.defect_material")
    preferred = raw(facts, "purchase.preferred_secondary_remedy")
    remedies = ["PRICE_REDUCTION", "TERMINATION_SUBJECT_TO_NON_MINOR_DEFECT"]
    claimable = 0.0
    next_action = "CHOOSE_SECONDARY_REMEDY"
    if preferred == "termination":
        next_action = "PREPARE_C02_TERMINATION"
        if material is True and price is not None:
            claimable = price
        elif material is not True:
            counterarguments.append({
                "type": "MINOR_DEFECT_MAY_BAR_TERMINATION", "status": "potential",
                "impact": "material", "origin": "known_rule",
            })
    elif preferred == "price_reduction":
        next_action = "PREPARE_C02_PRICE_REDUCTION"
        counterarguments.append({
            "type": "PRICE_REDUCTION_REQUIRES_PROPORTIONAL_VALUATION", "status": "open",
            "impact": "material", "origin": "calculation",
        })

    open_critical = any(c.get("status") == "open" and c.get("impact") == "critical" for c in counterarguments)
    viability = "MEDIUM" if open_critical else "HIGH"
    reasoning = (
        "Después de un intento de puesta en conformidad ha aparecido otra falta de conformidad, o el vendedor ha declarado que no la pondrá en conformidad. "
        "El artículo 119 permite en estos supuestos acceder a reducción proporcional del precio o, si la falta no es de escasa importancia, a la resolución del contrato."
    )
    if trigger == "seller_refusal":
        reasoning = (
            "El vendedor ha declarado que no pondrá el bien en conformidad. El artículo 119 contempla este supuesto para acceder a reducción del precio o resolución, con el límite de la escasa importancia para la resolución."
        )

    return EngineResult(
        viability=viability, scope_status="SUPPORTED", claimable_amount=claimable,
        economic_value=price, worth_pursuing=_worth(price), reasoning_summary=reasoning,
        counterarguments=counterarguments, missing_facts=[], next_action=next_action,
        rule_result="APPLIES", failed_conditions=[],
        calculation={"type": "c02_secondary_remedy", "preferred_remedy": preferred, "price": price, "trigger": trigger},
        sources=sources, remedies=remedies, burden_of_proof=burden,
    )
