from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

EU261_URL = "https://eur-lex.europa.eu/eli/reg/2004/261/oj"
# Product safety guard, not a statement of the reform's legal entry-into-force date.
# The 2026 amending regulation was finally adopted but had not yet been published
# as an applicable act when this rule was reviewed. Force re-review well before
# the earliest plausible application window instead of silently carrying old law.
CURRENT_RULE_REVIEW_BEFORE = date(2027, 7, 13)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def evaluate_v01(facts: dict[str, FactValue]) -> EngineResult:
    """V01 — refund for an airline-cancelled, EU-departing single-flight booking.

    This first travel family intentionally excludes inbound third-country scope,
    package-travel interactions, multi-segment pricing and Article 7 compensation.
    Those branches require separate rules or human review rather than inference.
    """
    sources = [{
        "title": "Reglamento (CE) n.º 261/2004, arts. 3, 5.1(a) y 8.1(a)",
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
                "La regla V01 está bloqueada por una revisión normativa programada antes de la futura aplicación "
                "de la reforma europea aprobada en 2026. Debe verificarse la versión jurídica vigente antes de continuar."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_LEGAL_TRANSITION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={"rule_review_before": CURRENT_RULE_REVIEW_BEFORE.isoformat()},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    cancelled = raw(facts, "travel.flight_cancelled_by_operating_carrier")
    if cancelled is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta confirmar si el vuelo fue cancelado por el transportista aéreo encargado de efectuarlo.",
            counterarguments=[],
            missing_facts=["travel.flight_cancelled_by_operating_carrier"],
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if cancelled is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="V01 solo cubre vuelos cancelados; retrasos, denegación de embarque y otros problemas tienen reglas distintas.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V01_NO_CARRIER_CANCELLATION",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["carrier_cancellation_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    missing: list[str] = []
    departure_in_eu = raw(facts, "travel.departure_airport_in_eu")
    confirmed = raw(facts, "travel.confirmed_reservation")
    fare_status = raw(facts, "travel.fare_status")
    package_trip = raw(facts, "travel.package_trip")
    booking_scope = raw(facts, "travel.booking_scope")
    passenger_choice = raw(facts, "travel.passenger_choice")
    notice_date = _parse_date(raw(facts, "travel.cancellation_notified_date"))

    for key, value in [
        ("travel.departure_airport_in_eu", departure_in_eu),
        ("travel.confirmed_reservation", confirmed),
        ("travel.fare_status", fare_status),
        ("travel.package_trip", package_trip),
        ("travel.booking_scope", booking_scope),
        ("travel.passenger_choice", passenger_choice),
        ("travel.cancellation_notified_date", notice_date),
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
            reasoning_summary="Faltan datos de ámbito, reserva o elección del pasajero necesarios para aplicar V01 de forma segura.",
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

    if notice_date and notice_date > analysis_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha confirmada de comunicación de la cancelación es posterior a la fecha de análisis y requiere revisión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
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
            reasoning_summary=(
                "V01 automatiza únicamente salidas desde aeropuertos de la UE. Algunos vuelos desde terceros países "
                "hacia la UE también pueden quedar cubiertos según el transportista y otras circunstancias, por lo que no se descartan."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_INBOUND_SCOPE",
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
            reasoning_summary="El artículo 3 exige una reserva confirmada para la aplicación de esta ruta automatizada.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V01_NO_CONFIRMED_RESERVATION",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["confirmed_reservation_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if fare_status == "unknown":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No está claro si el billete entra en el ámbito del artículo 3.3; V01 no presume que esté cubierto.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_FARE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
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
            reasoning_summary=(
                "El artículo 3.3 excluye los viajes gratuitos o con tarifa reducida no disponible al público, "
                "sin perjuicio de los billetes de programas de viajero frecuente u otros programas comerciales."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V01_NONPUBLIC_FARE_EXCLUSION",
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
            reasoning_summary="El tipo de tarifa indicado no está cubierto por la automatización segura de V01.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_FARE_SCOPE",
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
            reasoning_summary=(
                "El artículo 8.2 prevé una interacción específica con los viajes combinados. V01 no decide automáticamente "
                "qué obligado ni qué régimen de reembolso corresponde en ese supuesto."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_PACKAGE_TRAVEL",
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
            reasoning_summary=(
                "En reservas de ida y vuelta o varios tramos, el importe reembolsable depende de qué partes no se efectuaron "
                "y de si las partes ya realizadas dejaron de tener razón de ser para el plan de viaje. V01 no inventa ese reparto."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_MULTI_SEGMENT_REFUND",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if passenger_choice in {"rerouting_soonest", "rerouting_later"}:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "El artículo 8 ofrece alternativas entre reembolso y transporte alternativo. Según el objetivo confirmado, "
                "el pasajero ha elegido transporte alternativo y V01 no sustituye esa elección por una reclamación de reembolso."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V01_REROUTING_CHOICE",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=["REROUTING_OPTION_SELECTED"],
            burden_of_proof=[],
        )
    if passenger_choice != "refund":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No consta una elección clara entre reembolso y transporte alternativo.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_PASSENGER_CHOICE",
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
        received_amount_value = _money(raw(facts, "travel.refund_received_amount"))
        if received_amount_value is None:
            missing_money.append("travel.refund_received_amount")
        else:
            received_amount = max(received_amount_value, 0.0)

    if missing_money:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=ticket_price,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta el precio documentado del vuelo o el importe ya reembolsado para cuantificar el saldo pendiente.",
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
            reasoning_summary="El precio documentado no permite cuantificar de forma fiable un reembolso monetario.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V01_INVALID_TICKET_PRICE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    outstanding = round(max(ticket_price - received_amount, 0.0), 2)
    calculation = {
        "type": "single_flight_cancellation_refund",
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
            reasoning_summary="El reembolso acreditado ya alcanza el precio documentado del vuelo cancelado.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V01_ALREADY_REFUNDED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_CANCELLATION_REFUND_ALREADY_PAID"],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=ticket_price,
        worth_pursuing="YES_IF_LOW_COST" if outstanding < 50 else "YES",
        reasoning_summary=(
            "Para una cancelación cubierta, el artículo 5.1(a) remite al artículo 8: el pasajero debe poder elegir el "
            "reembolso y el artículo 8.1(a) prevé el reembolso en siete días del coste íntegro del billete correspondiente "
            "al vuelo no efectuado. V01 no está calculando aquí la compensación adicional del artículo 7."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_V01_CANCELLATION_REFUND",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["REFUND_CANCELLED_FLIGHT_TICKET"],
        burden_of_proof=[],
    )
