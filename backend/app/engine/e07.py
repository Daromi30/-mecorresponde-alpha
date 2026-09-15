from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD88_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88/con"
CURRENT_RULE_EFFECTIVE = date(2026, 6, 12)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _days_between(start: date | None, end: date | None) -> int | None:
    if not start or not end:
        return None
    return (end - start).days


def _noncompliant(
    *,
    reasoning: str,
    next_action: str,
    sources: list[dict[str, str]],
    counterarguments: list[dict[str, Any]],
    remedies: list[str],
) -> EngineResult:
    open_material = any(
        c.get("status") == "open" and c.get("impact") in {"material", "critical"}
        for c in counterarguments
    )
    return EngineResult(
        viability="MEDIUM" if open_material else "HIGH",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=None,
        worth_pursuing="YES_IF_LOW_COST",
        reasoning_summary=reasoning,
        counterarguments=counterarguments,
        missing_facts=[],
        next_action=next_action,
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=None,
        sources=sources,
        remedies=remedies,
        burden_of_proof=[{
            "issue": "contract_change_or_price_review_notice",
            "on": "supplier_and_case_evidence",
            "basis": "RD88_2026_6_30_DT7",
            "note": "Deben conservarse contrato, cláusula de revisión y comunicación recibida para comprobar contenido, fecha y separación de la factura.",
        }],
    )


def evaluate_e07(facts: dict[str, FactValue]) -> EngineResult:
    """E07 — unilateral condition changes and contractual price reviews.

    The engine distinguishes a true contract modification from a price review
    already contemplated by a transparent contractual formula. Monetary
    overbilling is intentionally delegated to E02-A once the correct amount is
    evidenced.
    """
    sources = [{
        "title": "RD 88/2026, arts. 6.1.m-n, 30.1.i-j y DT 7ª",
        "url": RD88_URL,
    }]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    effective_date = _parse_date(raw(facts, "electricity.contract_change_effective_date"))
    kind = raw(facts, "electricity.contract_change_kind")

    if effective_date is None:
        missing.append("electricity.contract_change_effective_date")
    elif effective_date < CURRENT_RULE_EFFECTIVE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LEGACY_REVIEW",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El cambio o revisión es anterior al 12/06/2026, fecha desde la que surten efectos los artículos 6 y 30 del RD 88/2026. Debe revisarse el régimen temporal anterior.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY",
            failed_conditions=["change_before_2026-06-12"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if kind is None:
        missing.append("electricity.contract_change_kind")

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan datos para distinguir una modificación de condiciones contractuales de una revisión de precio ya prevista por una fórmula del contrato.",
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

    if raw(facts, "company.asserts_notice_compliant", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_COMPLIANT_NOTICE",
            "status": "open",
            "impact": "material",
            "origin": "company_response",
        })
    if raw(facts, "company.asserts_contractual_price_formula", False):
        counterarguments.append({
            "type": "SUPPLIER_ASSERTS_CONTRACTUAL_PRICE_FORMULA",
            "status": "open",
            "impact": "material",
            "origin": "company_response",
        })

    notice_received = raw(facts, "electricity.change_notice_received")
    notice_date = _parse_date(raw(facts, "electricity.change_notice_date"))
    separate = raw(facts, "electricity.change_notice_separate_from_invoice")

    base_missing: list[str] = []
    if notice_received is None:
        base_missing.append("electricity.change_notice_received")
    if notice_received is True:
        if notice_date is None:
            base_missing.append("electricity.change_notice_date")
        if separate is None:
            base_missing.append("electricity.change_notice_separate_from_invoice")

    if kind == "contract_condition_change":
        free_exit = raw(facts, "electricity.notice_informed_free_termination_right")
        if free_exit is None:
            base_missing.append("electricity.notice_informed_free_termination_right")
        if base_missing:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=None,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Para una modificación de condiciones hay que comprobar si existió aviso escrito separado, con al menos un mes de antelación, y si informó del derecho a rescindir sin coste.",
                counterarguments=counterarguments,
                missing_facts=sorted(set(base_missing)),
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )

        days = _days_between(notice_date, effective_date) if notice_received else None
        defects: list[str] = []
        if notice_received is False:
            defects.append("no_prior_notice")
        else:
            if days is None or days < 30:
                defects.append("less_than_one_month_notice")
            if separate is False:
                defects.append("notice_not_separate_from_invoice")
        if free_exit is False:
            defects.append("free_termination_right_not_disclosed")

        if defects:
            return _noncompliant(
                reasoning=(
                    "La modificación contractual no cumple todos los requisitos de comunicación del artículo 6.1.m: aviso transparente y comprensible, por escrito y separado de la factura, con al menos un mes de antelación, e información del derecho a rescindir sin coste. "
                    f"Incidencias detectadas: {', '.join(defects)}."
                ),
                next_action="PREPARE_E07_CHANGE_CHALLENGE",
                sources=sources,
                counterarguments=counterarguments,
                remedies=["REQUEST_COMPLIANT_PRIOR_NOTICE", "TERMINATE_WITHOUT_COST", "DISPUTE_CHANGE_UNTIL_REVIEWED"],
            )

        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Consta una comunicación previa con al menos un mes de antelación, separada de la factura y con información del derecho a rescindir sin coste. Con esos hechos, la comunicación de la modificación aparece formalmente alineada con el artículo 6.1.m; ello no valida por sí solo cualquier cálculo económico posterior.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="EXPLAIN_VALID_NOTICE_AND_EXIT_RIGHT",
            rule_result="FAILED",
            failed_conditions=["notice_requirements_satisfied"],
            calculation={"type": "contract_change_notice", "notice_days": days},
            sources=sources,
            remedies=["TERMINATE_WITHOUT_COST"],
            burden_of_proof=[],
        )

    if kind != "contractual_price_review":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El tipo de cambio contractual no coincide con los dos supuestos automatizados de E07.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="HUMAN_REVIEW_CONTRACT_CHANGE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    fixed_price = raw(facts, "electricity.fixed_price_contract")
    formula = raw(facts, "electricity.price_review_formula_preagreed")
    if fixed_price is None:
        base_missing.append("electricity.fixed_price_contract")
    if formula is None:
        base_missing.append("electricity.price_review_formula_preagreed")

    if fixed_price is True:
        within_fixed_period = raw(facts, "electricity.price_review_within_fixed_price_period")
        if within_fixed_period is None:
            base_missing.append("electricity.price_review_within_fixed_price_period")
        elif within_fixed_period is True:
            return _noncompliant(
                reasoning="La revisión pretende aplicarse dentro de un periodo de precio fijo. El artículo 30.1.i excluye las cláusulas de revisión de condiciones en los contratos a precio fijo; debe revisarse si en realidad se está intentando una modificación contractual distinta.",
                next_action="PREPARE_E07_FIXED_PRICE_CHALLENGE",
                sources=sources,
                counterarguments=counterarguments,
                remedies=["DISPUTE_PRICE_REVIEW", "REQUEST_CONTRACT_COMPLIANCE"],
            )

    if formula is False:
        return EngineResult(
            viability="RECLASSIFY",
            scope_status="REDIRECT_CONDITION_CHANGE",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="No consta una fórmula de revisión pactada previamente. El cambio debe analizarse como modificación de condiciones contractuales, no como simple revisión derivada del contrato.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="RECLASSIFY_E07_CONDITION_CHANGE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["no_preagreed_price_review_formula"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    content_complete = raw(facts, "electricity.price_review_transitional_content_complete")
    reasons_scope = raw(facts, "electricity.price_review_reasons_scope_explained")
    if content_complete is None:
        base_missing.append("electricity.price_review_transitional_content_complete")
    if reasons_scope is None:
        base_missing.append("electricity.price_review_reasons_scope_explained")

    if base_missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Para validar una revisión contractual de precio hay que comprobar la cláusula previa y la comunicación: antelación, separación de la factura, razones y alcance, comparación de precios y estimación anual exigidas por la disposición transitoria séptima.",
            counterarguments=counterarguments,
            missing_facts=sorted(set(base_missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    days = _days_between(notice_date, effective_date) if notice_received else None
    defects: list[str] = []
    if notice_received is False:
        defects.append("no_price_review_notice")
    else:
        if days is None or days < 30:
            defects.append("less_than_one_month_notice")
        if separate is False:
            defects.append("notice_not_separate")
    if reasons_scope is False:
        defects.append("reasons_or_scope_missing")
    if content_complete is False:
        defects.append("transitional_comparison_content_incomplete")

    if defects:
        return _noncompliant(
            reasoning=(
                "La revisión de precio parte de una fórmula contractual, pero la comunicación no cumple todos los requisitos del artículo 6.1.n y de la disposición transitoria séptima. "
                f"Incidencias detectadas: {', '.join(defects)}. La alpha no convierte automáticamente este defecto de comunicación en una devolución monetaria; si ya se ha facturado un exceso verificable, se calcula por E02-A."
            ),
            next_action="PREPARE_E07_PRICE_REVIEW_CHALLENGE",
            sources=sources,
            counterarguments=counterarguments,
            remedies=["REQUEST_COMPLIANT_PRICE_REVIEW_NOTICE", "DISPUTE_REVIEW_APPLICATION", "RECALCULATE_IF_OVERBILLED"],
        )

    return EngineResult(
        viability="LOW",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=None,
        worth_pursuing="NO_PAID_MANAGEMENT",
        reasoning_summary="Consta una fórmula de revisión pactada y una comunicación con al menos un mes de antelación, separada de la factura, que explica razones y alcance e incorpora el contenido comparativo transitorio. Con esos hechos, E07 no detecta un defecto procedimental; cualquier error aritmético concreto debe analizarse por facturación.",
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="EXPLAIN_PROCEDURALLY_COMPLIANT_PRICE_REVIEW",
        rule_result="FAILED",
        failed_conditions=["price_review_notice_requirements_satisfied"],
        calculation={"type": "contractual_price_review_notice", "notice_days": days},
        sources=sources,
        remedies=[],
        burden_of_proof=[],
    )
