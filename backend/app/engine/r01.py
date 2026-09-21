from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

LAU_URL = "https://www.boe.es/eli/es/l/1994/11/24/29/con"


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


def _plus_one_calendar_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_r01(facts: dict[str, FactValue]) -> EngineResult:
    """R01 — narrow refund route for a documented refundable rental-deposit balance.

    This route deliberately does not decide landlord deductions, damage, unpaid rent,
    utilities, additional guarantees or whether a disputed balance is actually due.
    """
    sources = [{"title": "Ley 29/1994 de Arrendamientos Urbanos, art. 36.4", "url": LAU_URL}]

    contract_type = raw(facts, "rental.contract_type")
    lease_ended = raw(facts, "rental.lease_ended")
    keys_date = _parse_date(raw(facts, "rental.keys_delivered_date"))
    keys_proof = raw(facts, "rental.keys_delivery_proof_available")
    deposit_type = raw(facts, "rental.deposit_type")
    balance_status = raw(facts, "rental.refundable_balance_status")
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    missing: list[str] = []
    for key, value in [
        ("rental.contract_type", contract_type),
        ("rental.lease_ended", lease_ended),
        ("rental.keys_delivered_date", keys_date),
        ("rental.keys_delivery_proof_available", keys_proof),
        ("rental.deposit_type", deposit_type),
        ("rental.refundable_balance_status", balance_status),
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
            reasoning_summary="Faltan hechos básicos para determinar si R01 puede aplicar el artículo 36.4 de la LAU.",
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

    if contract_type not in {"dwelling", "other_urban_use"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "R01 automatiza únicamente arrendamientos urbanos identificados como vivienda o uso distinto de vivienda. "
                "Habitaciones, alquiler turístico o contratos de naturaleza dudosa requieren revisar el régimen aplicable."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_CONTRACT_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if lease_ended is not True:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="R01 solo analiza la restitución de la fianza al final del arrendamiento.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_R01_LEASE_NOT_ENDED",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["lease_end_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert keys_date is not None
    if keys_date > analysis_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha de entrega de llaves es posterior a la fecha de análisis y requiere revisión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if keys_proof is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 36.4 conecta el devengo del interés legal con el transcurso de un mes desde la entrega de llaves. "
                "Sin una fecha de entrega acreditable R01 no automatiza esa consecuencia."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_KEYS_DATE_EVIDENCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if deposit_type != "statutory_cash_deposit":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "R01 solo automatiza la fianza en metálico del artículo 36. Las garantías adicionales o importes mixtos "
                "pueden tener reglas contractuales distintas."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_DEPOSIT_TYPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if balance_status != "confirmed_amount":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 36.4 se refiere al saldo que deba ser restituido. Si existen deducciones discutidas, daños, "
                "rentas, suministros o no está determinado el saldo, R01 no presume qué importe corresponde devolver."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_REFUNDABLE_BALANCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    balance = _money(raw(facts, "rental.confirmed_refundable_balance"))
    refunded = raw(facts, "rental.refund_received")
    money_missing: list[str] = []
    if balance is None:
        money_missing.append("rental.confirmed_refundable_balance")
    if refunded is None:
        money_missing.append("rental.refund_received")

    received = 0.0
    if refunded is True:
        received_value = _money(raw(facts, "rental.refund_received_amount"))
        if received_value is None:
            money_missing.append("rental.refund_received_amount")
        else:
            received = max(received_value, 0.0)

    if money_missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=balance,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta el saldo de fianza confirmado o el importe ya restituido para calcular lo pendiente.",
            counterarguments=[],
            missing_facts=sorted(set(money_missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert balance is not None
    if balance < 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=balance,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El saldo confirmado no puede ser negativo en la ruta automatizada de restitución.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_INVALID_BALANCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    outstanding = round(max(balance - received, 0.0), 2)
    interest_start = _plus_one_calendar_month(keys_date)
    interest_accrues = analysis_date >= interest_start and outstanding > 0
    calculation = {
        "confirmed_refundable_balance": balance,
        "already_refunded": round(received, 2),
        "outstanding_balance": outstanding,
        "keys_delivered_date": keys_date.isoformat(),
        "legal_interest_from": interest_start.isoformat(),
        "legal_interest_accrues": interest_accrues,
        "legal_interest_amount_calculated": False,
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=balance,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La restitución acreditada ya cubre el saldo de fianza confirmado.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_R01_ALREADY_REFUNDED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_RENTAL_DEPOSIT_ALREADY_RETURNED"],
            burden_of_proof=[],
        )

    summary = (
        "Existe un saldo de fianza en metálico confirmado y pendiente de restitución al finalizar el arrendamiento. "
        "R01 solicita únicamente ese saldo documentado."
    )
    if interest_accrues:
        summary += (
            " Además, ha transcurrido un mes desde la entrega acreditada de llaves, por lo que el artículo 36.4 "
            "establece el devengo del interés legal; R01 no calcula automáticamente su cuantía."
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=balance,
        worth_pursuing="YES_IF_LOW_COST" if outstanding < 50 else "YES",
        reasoning_summary=summary,
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_R01_RENTAL_DEPOSIT_RETURN",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["RETURN_CONFIRMED_RENTAL_DEPOSIT_BALANCE"],
        burden_of_proof=[],
    )
