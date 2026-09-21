from __future__ import annotations

from typing import Any

from .common import EngineResult, FactValue, raw

RD899_URL = "https://www.boe.es/eli/es/rd/2009/05/22/899"


def _worth(amount: float | None) -> str:
    if amount is None:
        return "NEEDS_INFORMATION"
    if amount < 30:
        return "YES_IF_LOW_COST"
    return "YES"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_t01(facts: dict[str, FactValue]) -> EngineResult:
    """T01 — temporary interruption of fixed internet access.

    Automated scope is deliberately narrow: a subscriber with a fixed internet
    access service whose temporary interruption has ended. Mobile-internet
    attribution and unresolved/ongoing outages are routed to human review.
    """
    sources = [{"title": "Real Decreto 899/2009, art. 16", "url": RD899_URL}]
    missing: list[str] = []

    subscriber = raw(facts, "telecom.subscriber_has_contract")
    service_kind = raw(facts, "telecom.service_kind")
    restored = raw(facts, "telecom.service_restored")

    if subscriber is None:
        missing.append("telecom.subscriber_has_contract")
    if service_kind is None:
        missing.append("telecom.service_kind")
    if subscriber is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="T01 exige que la persona afectada sea abonada de un servicio de acceso a internet.",
            counterarguments=[],
            missing_facts=[],
            next_action="REDIRECT_NON_SUBSCRIBER_TELECOM_CASE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["subscriber_contract_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if service_kind == "mobile_internet":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La interrupción de internet móvil exige además determinar si el abonado se considera afectado "
                "conforme al artículo 17 del Real Decreto 899/2009. Esa atribución no se automatiza todavía."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_MOBILE_INTERRUPTION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if service_kind not in {None, "fixed_internet"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El tipo de servicio indicado no encaja en el alcance automatizado de T01.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_TELECOM_SERVICE_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if restored is None:
        missing.append("telecom.service_restored")
    if restored is False:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "T01 calcula la compensación de una interrupción temporal ya finalizada. "
                "Una falta de servicio todavía abierta requiere otra ruta de resolución."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_ONGOING_INTERNET_OUTAGE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    duration = _number(raw(facts, "telecom.interruption_duration_hours"))
    daytime = _number(raw(facts, "telecom.affected_hours_8_22"))
    serious_breach = raw(facts, "telecom.interruption_due_to_serious_subscriber_breach")
    terminal_damage = raw(facts, "telecom.interruption_due_to_nonconforming_terminal_damage")
    fee_identified = raw(facts, "telecom.internet_fee_identified")
    compensation_applied = raw(facts, "telecom.compensation_already_applied")
    billing_days = _number(raw(facts, "telecom.billing_period_days"))

    for key, value in [
        ("telecom.interruption_duration_hours", duration),
        ("telecom.affected_hours_8_22", daytime),
        ("telecom.interruption_due_to_serious_subscriber_breach", serious_breach),
        ("telecom.interruption_due_to_nonconforming_terminal_damage", terminal_damage),
        ("telecom.internet_fee_identified", fee_identified),
        ("telecom.compensation_already_applied", compensation_applied),
        ("telecom.billing_period_days", billing_days),
    ]:
        if value is None:
            missing.append(key)

    if serious_breach is True or terminal_damage is True:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=0.0,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary=(
                "El artículo 16.2 excluye la compensación del artículo 16 cuando la interrupción deriva de un "
                "incumplimiento grave del abonado o de daños de red causados por equipos terminales no conformes."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_T01_STATUTORY_EXCLUSION",
            rule_result="FAILED",
            failed_conditions=["article_16_2_exclusion"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    monthly_fee: float | None = None
    fee_basis = "itemized_internet_fee"
    if fee_identified is True:
        monthly_fee = _number(raw(facts, "telecom.monthly_internet_fixed_fee"))
        if monthly_fee is None:
            missing.append("telecom.monthly_internet_fixed_fee")
    elif fee_identified is False:
        bundle_total = _number(raw(facts, "telecom.bundle_total_monthly_price"))
        sold_separately = raw(facts, "telecom.operator_sells_services_separately")
        if bundle_total is None:
            missing.append("telecom.bundle_total_monthly_price")
        if sold_separately is None:
            missing.append("telecom.operator_sells_services_separately")
        if sold_separately is True:
            return EngineResult(
                viability="PROFESSIONAL_REVIEW",
                scope_status="LIMITED_SCOPE",
                claimable_amount=None,
                economic_value=bundle_total,
                worth_pursuing="PROFESSIONAL_REVIEW",
                reasoning_summary=(
                    "Cuando el paquete no identifica el precio de internet pero el operador comercializa los servicios "
                    "por separado, el artículo 16.3 exige una asignación proporcional que T01 no calcula sin los precios "
                    "separados verificables de todos los servicios."
                ),
                counterarguments=[],
                missing_facts=[],
                next_action="HUMAN_REVIEW_BUNDLE_PRICE_ALLOCATION",
                rule_result="MANUAL_REVIEW",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        if sold_separately is False and bundle_total is not None:
            monthly_fee = round(bundle_total * 0.5, 2)
            fee_basis = "statutory_50_percent_bundle"

    received = 0.0
    if compensation_applied is True:
        received_raw = _number(raw(facts, "telecom.compensation_received_amount"))
        if received_raw is None:
            missing.append("telecom.compensation_received_amount")
        else:
            received = max(received_raw, 0.0)

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=monthly_fee,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan datos necesarios para reproducir de forma segura la compensación por la interrupción.",
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

    if duration is None or duration <= 0 or billing_days is None or billing_days <= 0 or monthly_fee is None or monthly_fee < 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=monthly_fee,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Los datos de duración, período de facturación o cuota no permiten un prorrateo fiable.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_INVALID_INTERRUPTION_CALCULATION_INPUTS",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    expected = round(monthly_fee * duration / (billing_days * 24.0), 2)
    outstanding = round(max(expected - received, 0.0), 2)
    automatic = bool(daytime is not None and daytime > 6.0)

    calculation = {
        "type": "fixed_internet_interruption_compensation",
        "monthly_internet_fixed_fee": round(monthly_fee, 2),
        "interruption_duration_hours": duration,
        "billing_period_days": billing_days,
        "fee_basis": fee_basis,
        "expected_compensation": expected,
        "already_compensated": round(received, 2),
        "outstanding_compensation": outstanding,
        "automatic_credit_threshold_met": automatic,
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=expected,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La compensación acreditada ya alcanza el prorrateo calculado para la interrupción.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_T01_ALREADY_COMPENSATED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_COMPENSATION_ALREADY_APPLIED"],
            burden_of_proof=[],
        )

    automatic_note = (
        " Además, las horas afectadas entre las 8 y las 22 superan seis, por lo que el artículo 16.1 "
        "prevé abono automático en la factura del período inmediato."
        if automatic
        else ""
    )
    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=expected,
        worth_pursuing=_worth(outstanding),
        reasoning_summary=(
            "El artículo 16 del Real Decreto 899/2009 prevé la devolución prorrateada de la cuota de abono "
            "y otras cuotas fijas durante la interrupción temporal del acceso a internet."
            + automatic_note
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_T01_INTERNET_INTERRUPTION_COMPENSATION",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["REFUND_PRORATED_FIXED_INTERNET_FEES"],
        burden_of_proof=[],
    )
