from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw
from .v01 import CURRENT_RULE_REVIEW_BEFORE

EU261_URL = "https://eur-lex.europa.eu/eli/reg/2004/261/oj"

_DISTANCE_BANDS = {
    "le_1500": (250.0, 2.0),
    "intra_eu_gt_1500": (400.0, 3.0),
    "other_1500_3500": (400.0, 3.0),
    "other_gt_3500": (600.0, 4.0),
}


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


def evaluate_v03(facts: dict[str, FactValue]) -> EngineResult:
    """V03 — involuntary denied boarding compensation under Regulation 261/2004.

    Automated scope is intentionally narrow: EU departure, confirmed reservation,
    presentation requirements met, involuntary refusal, no Article 2(j) reasonable
    ground, and a verified distance band. Any ambiguity fails closed.
    """
    sources = [{
        "title": "Reglamento (CE) n.º 261/2004, arts. 2(j), 3.2, 4.3 y 7",
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
                "V03 está bloqueada por la revisión normativa preventiva de derechos aéreos. "
                "Debe verificarse la versión aplicable antes de automatizar un caso posterior a esa fecha."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V03_LEGAL_TRANSITION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={"rule_review_before": CURRENT_RULE_REVIEW_BEFORE.isoformat()},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    denied = raw(facts, "travel.denied_boarding_involuntary")
    if denied is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta confirmar si el embarque fue denegado contra la voluntad del pasajero.",
            counterarguments=[],
            missing_facts=["travel.denied_boarding_involuntary"],
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if denied is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "El artículo 4 distingue al voluntario que renuncia a su reserva a cambio de beneficios "
                "de la denegación de embarque contra su voluntad. V03 solo automatiza esta segunda situación."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V03_VOLUNTARY_SURRENDER",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["involuntary_denied_boarding_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    departure_in_eu = raw(facts, "travel.departure_airport_in_eu")
    confirmed = raw(facts, "travel.confirmed_reservation")
    presentation_met = raw(facts, "travel.presentation_requirement_met")
    fare_status = raw(facts, "travel.fare_status")
    reason = raw(facts, "travel.denied_boarding_reason")
    distance_band = raw(facts, "travel.distance_band")
    rerouted = raw(facts, "travel.rerouted_to_final_destination")
    compensation_received = raw(facts, "travel.compensation_received")
    missing: list[str] = []
    for key, value in [
        ("travel.departure_airport_in_eu", departure_in_eu),
        ("travel.confirmed_reservation", confirmed),
        ("travel.presentation_requirement_met", presentation_met),
        ("travel.fare_status", fare_status),
        ("travel.denied_boarding_reason", reason),
        ("travel.distance_band", distance_band),
        ("travel.rerouted_to_final_destination", rerouted),
        ("travel.compensation_received", compensation_received),
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
            reasoning_summary="Faltan datos de ámbito, presentación, motivo o distancia necesarios para aplicar V03.",
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
            reasoning_summary=(
                "V03 automatiza únicamente salidas desde la UE. Algunos vuelos desde terceros países pueden "
                "estar cubiertos según el transportista y otras condiciones del artículo 3."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V03_INBOUND_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if confirmed is False or presentation_met is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "La definición de denegación de embarque remite a las condiciones de presentación del artículo 3.2. "
                "V03 no automatiza compensación si no consta reserva confirmada y presentación válida."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V03_PRESENTATION_SCOPE_NOT_MET",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["article_3_2_presentation_required"],
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
            reasoning_summary="La tarifa indicada encaja en la exclusión del artículo 3.3 para viajes no disponibles al público.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V03_NONPUBLIC_FARE_EXCLUSION",
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
            next_action="HUMAN_REVIEW_V03_FARE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if reason in {"health", "safety_security", "inadequate_travel_documents"}:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=None,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "El artículo 2(j) excluye de la definición de denegación de embarque los rechazos basados "
                "en motivos razonables como salud, seguridad o documentación de viaje inadecuada."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V03_REASONABLE_GROUND_EXCLUSION",
            rule_result="FAILED",
            failed_conditions=["article_2_j_reasonable_ground"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if reason != "operational_or_no_reason":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El motivo de la denegación no está suficientemente claro para descartar un motivo razonable del artículo 2(j).",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V03_DENIAL_REASON",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if distance_band not in _DISTANCE_BANDS:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No existe una banda de distancia verificada para calcular la compensación del artículo 7.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_V03_DISTANCE_BAND",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    base_amount, reduction_threshold = _DISTANCE_BANDS[distance_band]
    reduced = False
    arrival_delay = None
    if rerouted is True:
        arrival_delay = _number(raw(facts, "travel.rerouting_arrival_delay_hours"))
        if arrival_delay is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=base_amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta el retraso de llegada del transporte alternativo para comprobar la posible reducción del 50 %.",
                counterarguments=[],
                missing_facts=["travel.rerouting_arrival_delay_hours"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if arrival_delay < 0:
            return EngineResult(
                viability="PROFESSIONAL_REVIEW",
                scope_status="LIMITED_SCOPE",
                claimable_amount=None,
                economic_value=base_amount,
                worth_pursuing="PROFESSIONAL_REVIEW",
                reasoning_summary="El retraso de llegada indicado no es coherente y requiere revisión.",
                counterarguments=[],
                missing_facts=[],
                next_action="HUMAN_REVIEW_V03_REROUTING_DELAY",
                rule_result="MANUAL_REVIEW",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        reduced = arrival_delay <= reduction_threshold

    statutory_amount = round(base_amount * (0.5 if reduced else 1.0), 2)
    received_amount = 0.0
    if compensation_received is True:
        received_amount = _number(raw(facts, "travel.compensation_received_amount"))
        if received_amount is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=statutory_amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta cuantificar la compensación ya recibida para calcular el saldo pendiente.",
                counterarguments=[],
                missing_facts=["travel.compensation_received_amount"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        received_amount = max(received_amount, 0.0)

    outstanding = round(max(statutory_amount - received_amount, 0.0), 2)
    calculation = {
        "type": "involuntary_denied_boarding_compensation",
        "distance_band": distance_band,
        "base_compensation": base_amount,
        "rerouting_arrival_delay_hours": arrival_delay,
        "reduction_threshold_hours": reduction_threshold,
        "article_7_2_reduction_applied": reduced,
        "statutory_compensation": statutory_amount,
        "already_compensated": round(received_amount, 2),
        "outstanding_compensation": outstanding,
        "rule_review_before": CURRENT_RULE_REVIEW_BEFORE.isoformat(),
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=statutory_amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La compensación acreditada ya alcanza la cuantía calculada conforme al artículo 7.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_V03_ALREADY_COMPENSATED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_DENIED_BOARDING_COMPENSATION_ALREADY_PAID"],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=statutory_amount,
        worth_pursuing="YES",
        reasoning_summary=(
            "El artículo 4.3 obliga a compensar inmediatamente conforme al artículo 7 cuando el embarque se deniega "
            "contra la voluntad del pasajero. La cuantía se calcula por la banda de distancia confirmada"
            + (
                " y se aplica la reducción del 50 % del artículo 7.2 por el tiempo de llegada del transporte alternativo."
                if reduced else "."
            )
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_V03_DENIED_BOARDING_COMPENSATION",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["ARTICLE_7_DENIED_BOARDING_COMPENSATION"],
        burden_of_proof=[],
    )
