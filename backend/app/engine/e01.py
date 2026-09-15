from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88/con"
TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"
CURRENT_RULE_EFFECTIVE = date(2026, 6, 12)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _supported(
    *,
    reasoning: str,
    next_action: str,
    sources: list[dict[str, str]],
    counterarguments: list[dict[str, Any]],
    economic_value: float | None,
    remedies: list[str],
) -> EngineResult:
    open_material = any(
        item.get("status") == "open" and item.get("impact") in {"material", "critical"}
        for item in counterarguments
    )
    return EngineResult(
        viability="MEDIUM" if open_material else "HIGH",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=economic_value,
        worth_pursuing="YES_IF_LOW_COST" if economic_value is None or economic_value < 30 else "YES",
        reasoning_summary=reasoning,
        counterarguments=counterarguments,
        missing_facts=[],
        next_action=next_action,
        rule_result="APPLIES",
        failed_conditions=[],
        calculation={
            "type": "pricing_contract_mismatch",
            "cash_amount_auto_calculated": False,
            "note": "La cuantía monetaria exige facturas, consumo y precios verificables; si se acredita, se calcula por facturación/E02-A.",
        },
        sources=sources,
        remedies=remedies,
        burden_of_proof=[{
            "issue": "contracted_or_offered_price_terms",
            "on": "case_evidence",
            "basis": "RD88_2026_30_AND_TRLGDCU_61",
            "note": "Debe conservarse contrato, oferta/promoción y factura para comparar lo ofertado/contratado con lo aplicado.",
        }],
    )


def evaluate_e01(facts: dict[str, FactValue]) -> EngineResult:
    """E01 — wrong contracted price/tariff/discount in electricity free market.

    This family does not duplicate E07: a newly introduced contractual change
    belongs to E07. E01 compares the already agreed/advertised economic terms
    with the price/tariff/discount actually applied.
    """
    sources = [
        {"title": "RD 88/2026, art. 30.1.i-k, q, u y w", "url": RD88_URL},
        {"title": "TRLGDCU, art. 61", "url": TRLGDCU_URL},
    ]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    issue_date = _parse_date(raw(facts, "electricity.pricing_issue_date"))
    consumer = raw(facts, "electricity.consumer_natural_person")
    market_type = raw(facts, "electricity.market_type")
    issue_type = raw(facts, "electricity.pricing_issue_type")
    evidence = raw(facts, "electricity.pricing_contract_or_offer_evidence_available")
    value_raw = raw(facts, "electricity.pricing_estimated_affected_amount")
    economic_value = round(float(value_raw), 2) if value_raw is not None else None

    if issue_date is None:
        missing.append("electricity.pricing_issue_date")
    elif issue_date < CURRENT_RULE_EFFECTIVE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LEGACY_REVIEW",
            claimable_amount=None,
            economic_value=economic_value,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La discrepancia es anterior al 12/06/2026, fecha desde la que surte efectos el artículo 30 del RD 88/2026. El contenido de la oferta puede seguir siendo jurídicamente relevante, pero el régimen sectorial temporal debe revisarse antes de automatizar una conclusión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY",
            failed_conditions=["pricing_issue_before_2026-06-12"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if consumer is None:
        missing.append("electricity.consumer_natural_person")
    elif consumer is False:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=economic_value,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="E01 automatiza por ahora suministros domésticos de persona física. Un contrato empresarial requiere revisar el contrato y las reglas aplicables sin trasladar automáticamente protecciones de consumo.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_BUSINESS_PRICING",
            rule_result="MANUAL_REVIEW",
            failed_conditions=["non_consumer_scope"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if market_type is None:
        missing.append("electricity.market_type")
    elif market_type == "pvpc":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="PVPC_REVIEW",
            claimable_amount=None,
            economic_value=economic_value,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El precio PVPC se determina por normativa regulada y no debe analizarse como una discrepancia de oferta de mercado libre. Se deriva a la ruta específica de precio regulado.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_PVPC_PRICING",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["not_free_market"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if issue_type is None:
        missing.append("electricity.pricing_issue_type")
    if evidence is None:
        missing.append("electricity.pricing_contract_or_offer_evidence_available")

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=economic_value,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan datos materiales para comparar las condiciones económicas ofertadas/contratadas con las realmente aplicadas.",
            counterarguments=[],
            missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if evidence is False:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=economic_value,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="No hay todavía contrato, oferta, promoción o documento equivalente con el que comparar el precio, tarifa o descuento aplicado. Antes de afirmar una discrepancia hay que recuperar esa evidencia.",
            counterarguments=[],
            missing_facts=["electricity.pricing_contract_or_offer_evidence"],
            next_action="REQUEST_CONTRACT_OR_OFFER_EVIDENCE",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if raw(facts, "company.asserts_pricing_matches_contract", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_PRICING_MATCHES_CONTRACT",
            "status": "open",
            "impact": "material",
            "origin": "company_response",
        })

    if issue_type in {"contracted_price_mismatch", "tariff_mismatch"}:
        promised = raw(facts, "electricity.pricing_promised_terms")
        applied = raw(facts, "electricity.pricing_applied_terms")
        mismatch = raw(facts, "electricity.pricing_difference_confirmed")
        local_missing: list[str] = []
        if not promised:
            local_missing.append("electricity.pricing_promised_terms")
        if not applied:
            local_missing.append("electricity.pricing_applied_terms")
        if mismatch is None:
            local_missing.append("electricity.pricing_difference_confirmed")
        if local_missing:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=economic_value,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta completar la comparación entre el precio/tarifa documentado y el realmente aplicado.",
                counterarguments=counterarguments,
                missing_facts=local_missing,
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if mismatch is False:
            return EngineResult(
                viability="LOW",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=economic_value,
                worth_pursuing="NO_PAID_MANAGEMENT",
                reasoning_summary="La comparación confirmada no muestra diferencia entre las condiciones económicas documentadas y las aplicadas. E01 no sustenta una reclamación con los hechos actuales.",
                counterarguments=counterarguments,
                missing_facts=[],
                next_action="EXPLAIN_NO_PRICING_MISMATCH",
                rule_result="FAILED",
                failed_conditions=["no_verified_pricing_difference"],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        label = "tarifa/modalidad" if issue_type == "tariff_mismatch" else "precio"
        return _supported(
            reasoning=(
                f"La evidencia disponible muestra una diferencia entre el {label} ofertado o contratado y el aplicado. El artículo 30 exige condiciones económicas claras y transparentes, y el artículo 61 del TRLGDCU integra en el contrato el contenido económico de la oferta o promoción. "
                "La corrección económica exacta se calculará con las facturas y magnitudes verificables, no a partir de una estimación informal."
            ),
            next_action="PREPARE_E01_PRICING_CORRECTION",
            sources=sources,
            counterarguments=counterarguments,
            economic_value=economic_value,
            remedies=["APPLY_CONTRACTED_PRICE_OR_TARIFF", "REBILL_AFFECTED_PERIOD", "REFUND_VERIFIED_OVERCHARGE_IF_ANY"],
        )

    if issue_type == "discount_mismatch":
        terms_disclosed = raw(facts, "electricity.discount_duration_and_terms_disclosed")
        application_matches = raw(facts, "electricity.discount_application_matches_promised_terms")
        if terms_disclosed is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=economic_value,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Hay que comprobar si la oferta/contrato indicaba de forma expresa la duración del descuento y los términos o precios sobre los que se aplicaba.",
                counterarguments=counterarguments,
                missing_facts=["electricity.discount_duration_and_terms_disclosed"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if application_matches is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=economic_value,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta confirmar si el descuento aplicado —duración, porcentaje/base o fecha de finalización— coincide realmente con lo prometido/documentado.",
                counterarguments=counterarguments,
                missing_facts=["electricity.discount_application_matches_promised_terms"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if terms_disclosed is True and application_matches is True:
            return EngineResult(
                viability="LOW",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=economic_value,
                worth_pursuing="NO_PAID_MANAGEMENT",
                reasoning_summary="La duración y condiciones del descuento estaban documentadas y su aplicación coincide con esos términos. E01 no detecta una discrepancia exigible con los hechos actuales.",
                counterarguments=counterarguments,
                missing_facts=[],
                next_action="EXPLAIN_DISCOUNT_APPLIED_AS_AGREED",
                rule_result="FAILED",
                failed_conditions=["discount_matches_disclosed_terms"],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )

        if terms_disclosed is False:
            reasoning = (
                "La oferta/contrato no refleja de forma completa y transparente la duración del descuento promocional o los términos/precios sobre los que se aplica, información que el artículo 30.1.k exige especificar expresamente. "
                "Antes de fijar una devolución concreta debe reconstruirse el efecto económico con facturas y la oferta disponible."
            )
        else:
            reasoning = (
                "El descuento aplicado no coincide con las condiciones promocionales documentadas. El artículo 30.1.k exige transparencia sobre su duración y base de aplicación, y el artículo 61 del TRLGDCU hace exigible el contenido económico de la oferta/promoción. "
                "La cuantía exacta se calculará solo con facturación verificable."
            )
        return _supported(
            reasoning=reasoning,
            next_action="PREPARE_E01_DISCOUNT_CORRECTION",
            sources=sources,
            counterarguments=counterarguments,
            economic_value=economic_value,
            remedies=["APPLY_PROMISED_DISCOUNT", "REBILL_AFFECTED_PERIOD", "REFUND_VERIFIED_OVERCHARGE_IF_ANY"],
        )

    return EngineResult(
        viability="PROFESSIONAL_REVIEW",
        scope_status="LIMITED_SCOPE",
        claimable_amount=None,
        economic_value=economic_value,
        worth_pursuing="PROFESSIONAL_REVIEW",
        reasoning_summary="La discrepancia de precio descrita no encaja todavía en los supuestos estructurados de E01.",
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="HUMAN_REVIEW_PRICING_ISSUE",
        rule_result="MANUAL_REVIEW",
        failed_conditions=[],
        calculation=None,
        sources=sources,
        remedies=[],
        burden_of_proof=[],
    )
