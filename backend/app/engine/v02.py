from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw
from .v01 import CURRENT_RULE_REVIEW_BEFORE

EU261_URL = "https://eur-lex.europa.eu/eli/reg/2004/261/oj"


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


def _money(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else round(number, 2)


def evaluate_v02(facts: dict[str, FactValue]) -> EngineResult:
    """V02 — Article 6 five-hour delay route to Article 8.1(a) reimbursement.

    Automated scope is intentionally narrower than the Regulation: EU departure,
    confirmed public/programme fare, single-flight price, no package travel, and
    the passenger did not take the delayed flight after choosing reimbursement.
    """
    sources = [{
        "title": "Reglamento (CE) n.º 261/2004, arts. 3, 6.1(iii) y 8.1(a)",
        "url": EU261_URL,
    }]
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    if analysis_date >= CURRENT_RULE_REVIEW_BEFORE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "V02 está bloqueada por la misma revisión normativa preventiva de derechos aéreos que V01. "
                "Debe verificarse la versión aplicable antes de automatizar un caso posterior a esa fecha."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_LEGAL_TRANSITION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={"rule_review_before": CURRENT_RULE_REVIEW_BEFORE.isoformat()},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    delay_hours = _number(raw(facts, "travel.departure_delay_hours"))
    if delay_hours is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta confirmar cuántas horas alcanzó el retraso en la salida.",
            counterarguments=[],
            missing_facts=["travel.departure_delay_hours"],
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if delay_hours < 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La duración indicada del retraso no es coherente y requiere revisión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_INVALID_DELAY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if delay_hours < 5:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "V02 automatiza únicamente el reembolso vinculado al retraso de al menos cinco horas previsto "
                "en el artículo 6.1(iii). Otros derechos por retrasos inferiores se analizan por rutas distintas."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V02_DELAY_BELOW_FIVE_HOURS",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["five_hour_delay_required"],
            calculation={"departure_delay_hours": delay_hours},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    departure_in_eu = raw(facts, "travel.departure_airport_in_eu")
    confirmed = raw(facts, "travel.confirmed_reservation")
    fare_status = raw(facts, "travel.fare_status")
    package_trip = raw(facts, "travel.package_trip")
    booking_scope = raw(facts, "travel.booking_scope")
    wants_refund = raw(facts, "travel.delay_refund_requested")
    took_flight = raw(facts, "travel.passenger_took_delayed_flight")
    missing: list[str] = []
    for key, value in [
        ("travel.departure_airport_in_eu", departure_in_eu),
        ("travel.confirmed_reservation", confirmed),
        ("travel.fare_status", fare_status),
        ("travel.package_trip", package_trip),
        ("travel.booking_scope", booking_scope),
        ("travel.delay_refund_requested", wants_refund),
        ("travel.passenger_took_delayed_flight", took_flight),
    ]:
        if value is None:
            missing.append(key)

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan datos de ámbito, reserva o elección necesarios para aplicar el reembolso por retraso de cinco horas.",
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

    if departure_in_eu is False:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="V02 automatiza únicamente salidas desde la UE; los vuelos desde terceros países requieren comprobar el ámbito del artículo 3.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_INBOUND_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if confirmed is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="La ruta automatizada exige una reserva confirmada dentro del ámbito del artículo 3.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V02_NO_CONFIRMED_RESERVATION",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["confirmed_reservation_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if fare_status == "nonpublic_free_or_reduced":
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="La tarifa indicada encaja en la exclusión del artículo 3.3 para viajes gratuitos o reducidos no disponibles al público.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V02_NONPUBLIC_FARE_EXCLUSION",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["article_3_3_nonpublic_fare"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if fare_status not in {"public_fare", "frequent_flyer_program"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El tipo de tarifa no permite confirmar automáticamente el ámbito del Reglamento.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_FARE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if package_trip is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El viaje combinado puede interactuar con otro régimen de reembolso; V02 no decide automáticamente esa concurrencia.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_PACKAGE_TRAVEL",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if booking_scope != "single_flight":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Una reserva multitramos o ida y vuelta requiere separar qué partes no se realizaron y su utilidad para el plan de viaje.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_MULTI_SEGMENT_REFUND",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if wants_refund is False:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="Aunque el retraso alcanzó cinco horas, el pasajero no quiere ejercer la opción de reembolso en esta ruta.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V02_REFUND_OPTION_NOT_SELECTED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation={"departure_delay_hours": delay_hours},
            sources=sources,
            remedies=["FIVE_HOUR_DELAY_REFUND_OPTION"],
            burden_of_proof=[],
        )
    if took_flight is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "V02 cuantifica automáticamente solo el vuelo que el pasajero dejó de tomar tras alcanzar el retraso de cinco horas. "
                "Si el vuelo se utilizó, debe revisarse si alguna parte del viaje dejó de tener razón de ser."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_FLOWN_SEGMENT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    ticket_price = _money(raw(facts, "travel.documented_ticket_price"))
    refund_received = raw(facts, "travel.refund_received")
    missing_money: list[str] = []
    if ticket_price is None:
        missing_money.append("travel.documented_ticket_price")
    if refund_received is None:
        missing_money.append("travel.refund_received")
    received_amount = 0.0
    if refund_received is True:
        received = _money(raw(facts, "travel.refund_received_amount"))
        if received is None:
            missing_money.append("travel.refund_received_amount")
        else:
            received_amount = max(received, 0.0)
    if missing_money:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=ticket_price,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta el precio documentado o el importe ya reembolsado para calcular el saldo pendiente.",
            counterarguments=[],
            missing_facts=sorted(set(missing_money)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    assert ticket_price is not None
    if ticket_price <= 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=ticket_price,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El precio documentado no permite cuantificar con seguridad el reembolso.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V02_INVALID_TICKET_PRICE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    outstanding = round(max(ticket_price - received_amount, 0.0), 2)
    calculation = {
        "type": "five_hour_delay_ticket_refund",
        "departure_delay_hours": delay_hours,
        "documented_ticket_price": ticket_price,
        "already_refunded": round(received_amount, 2),
        "outstanding_refund": outstanding,
        "article_8_refund_days": 7,
        "article_7_compensation_included": False,
        "rule_review_before": CURRENT_RULE_REVIEW_BEFORE.isoformat(),
    }
    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=ticket_price,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="El reembolso acreditado ya cubre el precio documentado del vuelo no utilizado.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V02_ALREADY_REFUNDED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_DELAY_REFUND_ALREADY_PAID"],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=ticket_price,
        worth_pursuing="YES_IF_LOW_COST" if outstanding < 50 else "YES",
        reasoning_summary=(
            "El artículo 6.1(iii) remite al artículo 8.1(a) cuando el retraso alcanza al menos cinco horas. "
            "En la ruta V02 el pasajero no utilizó el vuelo y eligió reembolso, que el artículo 8.1(a) prevé en siete días. "
            "No se calcula aquí una compensación adicional por retraso."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_V02_FIVE_HOUR_DELAY_REFUND",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["REFUND_FIVE_HOUR_DELAY_UNUSED_FLIGHT"],
        burden_of_proof=[],
    )
