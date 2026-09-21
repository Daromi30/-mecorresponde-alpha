from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

RD1457_URL = "https://www.boe.es/eli/es/rd/1986/01/10/1457/con"


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plus_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_a01(facts: dict[str, FactValue]) -> EngineResult:
    """A01 — narrow workshop repair-guarantee route under Article 16 RD 1457/1986."""
    sources = [{"title": "Real Decreto 1457/1986, art. 16", "url": RD1457_URL}]

    workshop_spain = raw(facts, "automotive.workshop_in_spain")
    vehicle_type = raw(facts, "automotive.vehicle_type")
    delivery_date = _parse_date(raw(facts, "automotive.repair_delivery_date"))
    documentation = raw(facts, "automotive.repair_documentation_available")
    failure_date = _parse_date(raw(facts, "automotive.failure_date"))
    km_since = _number(raw(facts, "automotive.km_since_repair"))
    part_status = raw(facts, "automotive.failure_repaired_part_status")
    third_party = raw(facts, "automotive.third_party_manipulation_after_repair")
    hidden_anomaly = raw(facts, "automotive.refused_hidden_anomaly_causal_status")

    required = {
        "automotive.workshop_in_spain": workshop_spain,
        "automotive.vehicle_type": vehicle_type,
        "automotive.repair_delivery_date": delivery_date,
        "automotive.repair_documentation_available": documentation,
        "automotive.failure_date": failure_date,
        "automotive.km_since_repair": km_since,
        "automotive.failure_repaired_part_status": part_status,
        "automotive.third_party_manipulation_after_repair": third_party,
        "automotive.refused_hidden_anomaly_causal_status": hidden_anomaly,
    }
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos esenciales para comprobar la garantía de la reparación del taller.",
            counterarguments=[],
            missing_facts=missing,
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if workshop_spain is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="A01 automatiza únicamente reparaciones efectuadas por talleres situados en España.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_TERRITORIAL_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if vehicle_type != "non_industrial":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "A01 automatiza inicialmente vehículos no industriales. El artículo 16 prevé un plazo distinto "
                "para vehículos industriales y requiere una ruta separada."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_VEHICLE_TYPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if documentation is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Sin factura, orden de reparación u otra documentación suficiente no puede fijarse de forma segura "
                "la fecha de entrega ni qué parte fue reparada."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_REPAIR_EVIDENCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert delivery_date is not None and failure_date is not None and km_since is not None
    if failure_date < delivery_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha de la avería es anterior a la entrega del vehículo reparado.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    expiry_date = _plus_calendar_months(delivery_date, 3)
    within_time = failure_date <= expiry_date
    within_km = 0 <= km_since <= 2000
    calculation = {
        "repair_delivery_date": delivery_date.isoformat(),
        "three_month_date": expiry_date.isoformat(),
        "failure_date": failure_date.isoformat(),
        "km_since_repair": km_since,
        "within_three_months": within_time,
        "within_2000_km": within_km,
    }

    if not within_time or not within_km:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "La avería indicada queda fuera del alcance automático de la garantía mínima de tres meses o 2.000 km "
                "que aplica A01, sin perjuicio de otros derechos que puedan existir."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_A01_MINIMUM_GUARANTEE_EXPIRED",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["repair_guarantee_window"],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if part_status == "different_part":
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "La nueva avería está identificada como ajena a la parte o partes reparadas; A01 no extiende "
                "automáticamente la garantía a una avería distinta."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_A01_DIFFERENT_PART",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["failure_on_repaired_part_required"],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if part_status != "same_repaired_part":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No está suficientemente acreditado que la nueva avería afecte a la parte o partes reparadas.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_REPAIRED_PART_CAUSATION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if third_party is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Consta una manipulación o reparación posterior por tercero y el artículo 16.2 condiciona la garantía "
                "a la ausencia de esa intervención. Debe revisarse la prueba antes de concluir."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_THIRD_PARTY_MANIPULATION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if hidden_anomaly in {"yes", "unknown"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Puede existir una anomalía o avería oculta previamente comunicada cuya reparación fue rechazada. "
                "El artículo 16.6 prevé una excepción cuando ese fallo sea causal y conste en factura."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_A01_REFUSED_HIDDEN_ANOMALY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=0.0,
        economic_value=None,
        worth_pursuing="YES_IF_LOW_COST",
        reasoning_summary=(
            "La avería aparece dentro de tres meses y 2.000 km, afecta a la parte reparada y no consta una intervención "
            "posterior de tercero ni la excepción automatizada por anomalía oculta rechazada. El artículo 16.4 obliga "
            "al taller garante, previa comunicación del usuario, a reparar gratuitamente esa avería."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_A01_FREE_REPAIR_NOTICE",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["FREE_REPAIR_UNDER_WORKSHOP_GUARANTEE"],
        burden_of_proof=[],
    )
