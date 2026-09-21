from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

LAU_URL = "https://www.boe.es/eli/es/l/1994/11/24/29/con"
LAU_EFFECTIVE_DATE = date(1995, 1, 1)


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


def evaluate_r01(facts: dict[str, FactValue]) -> EngineResult:
    """R01 — narrow return route for an uncontested rental cash deposit balance.

    The automated route only covers a lease within the LAU, ended with keys
    returned, a documented cash deposit and no landlord deduction currently
    asserted. Any alleged damage, rent, utility debt or other offset fails closed.
    Legal interest after one month is identified but not calculated automatically.
    """
    sources = [{"title": "Ley 29/1994 de Arrendamientos Urbanos, art. 36.4", "url": LAU_URL}]
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    lau_scope = raw(facts, "rental.lease_under_lau")
    lease_ended = raw(facts, "rental.lease_ended")
    keys_returned = raw(facts, "rental.keys_returned")
    keys_date = _parse_date(raw(facts, "rental.keys_return_date"))
    deposit_amount = _money(raw(facts, "rental.documented_cash_deposit_amount"))
    deductions = raw(facts, "rental.landlord_deduction_status")
    refunded = raw(facts, "rental.deposit_refund_received")

    required = {
        "rental.lease_under_lau": lau_scope,
        "rental.lease_ended": lease_ended,
        "rental.keys_returned": keys_returned,
        "rental.keys_return_date": keys_date,
        "rental.documented_cash_deposit_amount": deposit_amount,
        "rental.landlord_deduction_status": deductions,
        "rental.deposit_refund_received": refunded,
    }
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos necesarios para comprobar el saldo de la fianza y el fin del arrendamiento.",
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

    if lau_scope is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "R01 automatiza únicamente arrendamientos sometidos a la Ley de Arrendamientos Urbanos. "
                "Otros contratos de alojamiento, temporada atípica o regímenes especiales requieren revisión."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_LEASE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if lease_ended is not True or keys_returned is not True:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "El artículo 36.4 se refiere al saldo que deba restituirse al final del arriendo y conecta el interés "
                "con la entrega de llaves. R01 requiere que ambas circunstancias estén confirmadas."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_R01_LEASE_NOT_ENDED_OR_KEYS_NOT_RETURNED",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["lease_end_and_key_return_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert keys_date is not None
    if keys_date < LAU_EFFECTIVE_DATE or keys_date > analysis_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha de entrega de llaves no permite aplicar de forma segura la regla actual de R01.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_DATE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if deductions in {"asserted", "unknown"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 36.4 se refiere al saldo de la fianza que deba restituirse. Si el arrendador alega "
                "daños, rentas, suministros u otras compensaciones, el saldo debe determinarse antes de automatizar la cuantía."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_DEDUCTIONS",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if deductions != "none_asserted":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El estado de posibles descuentos no encaja en el contrato seguro de R01.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_DEDUCTIONS",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert deposit_amount is not None
    if deposit_amount <= 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=deposit_amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El importe documentado de la fianza no permite calcular una restitución fiable.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_R01_INVALID_DEPOSIT_AMOUNT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    received = 0.0
    if refunded is True:
        received_amount = _money(raw(facts, "rental.deposit_refund_received_amount"))
        if received_amount is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=deposit_amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta el importe ya restituido de la fianza.",
                counterarguments=[],
                missing_facts=["rental.deposit_refund_received_amount"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        received = max(received_amount, 0.0)

    outstanding = round(max(deposit_amount - received, 0.0), 2)
    days_since_keys = (analysis_date - keys_date).days
    interest_trigger_reached = days_since_keys > 30
    calculation = {
        "documented_cash_deposit_amount": deposit_amount,
        "already_refunded": round(received, 2),
        "outstanding_deposit": outstanding,
        "keys_return_date": keys_date.isoformat(),
        "days_since_keys_return": days_since_keys,
        "article_36_4_interest_trigger_reached": interest_trigger_reached,
        "legal_interest_amount_automated": False,
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=deposit_amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La restitución acreditada ya cubre el importe documentado de la fianza.",
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

    if not interest_trigger_reached:
        return EngineResult(
            viability="MEDIUM",
            scope_status="SUPPORTED",
            claimable_amount=outstanding,
            economic_value=deposit_amount,
            worth_pursuing="YES_IF_LOW_COST",
            reasoning_summary=(
                "Consta un saldo de fianza pendiente, pero todavía no ha transcurrido más de un mes desde la entrega de llaves. "
                "R01 puede identificar el principal pendiente, pero no afirma que haya comenzado a devengarse el interés legal del artículo 36.4."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="PREPARE_R01_DEPOSIT_RETURN_REQUEST",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["RETURN_RENTAL_DEPOSIT_BALANCE"],
            burden_of_proof=[],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=deposit_amount,
        worth_pursuing="YES" if outstanding >= 50 else "YES_IF_LOW_COST",
        reasoning_summary=(
            "El artículo 36.4 dispone que el saldo de la fianza que deba restituirse devenga el interés legal "
            "cuando ha transcurrido un mes desde la entrega de llaves sin restitución. R01 reclama el principal "
            "documentado pendiente y deja el cálculo del interés legal fuera de la automatización."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_R01_DEPOSIT_RETURN_REQUEST",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["RETURN_RENTAL_DEPOSIT_BALANCE", "LEGAL_INTEREST_NOT_AUTOMATICALLY_QUANTIFIED"],
        burden_of_proof=[],
    )
