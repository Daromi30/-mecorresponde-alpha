from __future__ import annotations

from datetime import date
from typing import Any

from .common import EngineResult, FactValue, raw

EHA2899_URL = "https://www.boe.es/eli/es/o/2011/10/28/eha2899/con"
RULE_EFFECTIVE_DATE = date(2012, 4, 29)


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_b03(facts: dict[str, FactValue]) -> EngineResult:
    """B03 — narrow Article 3.1 banking-fee validity gate.

    This route does not decide whether a fee is abusive or whether its amount is
    excessive. It only checks the two cumulative charging conditions expressly
    stated in Article 3.1 of Order EHA/2899/2011.
    """
    sources = [{"title": "Orden EHA/2899/2011, art. 3.1", "url": EHA2899_URL}]

    consumer = raw(facts, "bank.customer_is_consumer")
    credit_entity = raw(facts, "bank.entity_is_credit_institution")
    service_scope = raw(facts, "bank.commission_service_scope")
    charge_date = _date(raw(facts, "bank.commission_charge_date"))
    amount = _money(raw(facts, "bank.commission_amount"))
    request_status = raw(facts, "bank.commission_request_acceptance_status")
    performance_status = raw(facts, "bank.commission_service_performance_status")
    refunded = raw(facts, "bank.commission_refund_received")

    required = {
        "bank.customer_is_consumer": consumer,
        "bank.entity_is_credit_institution": credit_entity,
        "bank.commission_service_scope": service_scope,
        "bank.commission_charge_date": charge_date,
        "bank.commission_amount": amount,
        "bank.commission_request_acceptance_status": request_status,
        "bank.commission_service_performance_status": performance_status,
        "bank.commission_refund_received": refunded,
    }
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos esenciales para comprobar las condiciones de cobro de la comisión.",
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

    if consumer is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "B03 automatiza únicamente clientes consumidores. La Orden permite pactar excepciones de aplicación "
                "cuando el cliente actúa en su actividad profesional o empresarial."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_NON_CONSUMER_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if credit_entity is not True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="No está confirmado que la entidad y el servicio entren en el ámbito automatizado de la Orden EHA/2899/2011.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_ENTITY_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if service_scope != "ordinary_banking_service":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "B03 no automatiza comisiones de inversión, seguros u otros servicios con régimen sectorial propio."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_SERVICE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert charge_date is not None
    if charge_date < RULE_EFFECTIVE_DATE:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El cargo es anterior a la entrada en vigor de la regla automatizada de B03 y requiere reconstrucción normativa histórica.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_HISTORICAL_RULE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={"rule_effective_date": RULE_EFFECTIVE_DATE.isoformat()},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if request_status == "unknown" or performance_status == "unknown":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "No existe documentación suficiente para confirmar si el servicio fue solicitado/aceptado y efectivamente prestado o generó un gasto real."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_EVIDENCE_GAP",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if request_status not in {"accepted", "not_requested_or_accepted"} or performance_status not in {
        "provided_or_expense_incurred",
        "not_provided_or_no_expense",
    }:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Los estados documentales de la comisión no encajan en el contrato seguro de B03.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_EVIDENCE_GAP",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert amount is not None
    if amount <= 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El importe documentado no permite cuantificar una devolución fiable.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B03_INVALID_AMOUNT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    both_conditions_met = (
        request_status == "accepted"
        and performance_status == "provided_or_expense_incurred"
    )
    if both_conditions_met:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "La documentación confirma tanto la solicitud o aceptación del servicio como su prestación efectiva o gasto. "
                "B03 no concluye que la comisión sea improcedente por el artículo 3.1 ni valora si su cuantía es abusiva."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_B03_CHARGING_CONDITIONS_MET",
            rule_result="FAILED",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    received = 0.0
    if refunded is True:
        received_amount = _money(raw(facts, "bank.commission_refund_received_amount"))
        if received_amount is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta el importe ya devuelto de la comisión.",
                counterarguments=[],
                missing_facts=["bank.commission_refund_received_amount"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        received = max(received_amount, 0.0)

    outstanding = round(max(amount - received, 0.0), 2)
    calculation = {
        "documented_commission_amount": amount,
        "already_refunded": round(received, 2),
        "outstanding_refund": outstanding,
        "service_requested_or_accepted": request_status == "accepted",
        "service_or_expense_effective": performance_status == "provided_or_expense_incurred",
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La devolución acreditada ya cubre íntegramente la comisión documentada.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_B03_ALREADY_REFUNDED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_BANK_FEE_REFUND_ALREADY_PAID"],
            burden_of_proof=[],
        )

    missing_condition = (
        "no consta solicitud o aceptación expresa del servicio"
        if request_status == "not_requested_or_accepted"
        else "no consta servicio efectivamente prestado ni gasto habido"
    )
    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=amount,
        worth_pursuing="YES" if outstanding >= 50 else "YES_IF_LOW_COST",
        reasoning_summary=(
            f"El artículo 3.1 exige acumulativamente que la comisión responda a un servicio solicitado o aceptado "
            f"expresamente y a un servicio efectivamente prestado o gasto habido; {missing_condition}."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_B03_BANK_FEE_REFUND",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["REFUND_UNREQUESTED_OR_UNPROVIDED_BANK_FEE"],
        burden_of_proof=[],
    )
