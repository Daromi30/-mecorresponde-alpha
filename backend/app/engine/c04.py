from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .common import EngineResult, FactValue, raw

TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"
CURRENT_REGIME_START = date(2022, 1, 1)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _worth(amount: float | None) -> str:
    if amount is None:
        return "NEEDS_INFORMATION"
    if amount < 30:
        return "YES_IF_LOW_COST"
    return "YES"


def evaluate_c04(facts: dict[str, FactValue]) -> EngineResult:
    """C04 — physical consumer order not delivered.

    The automated slice intentionally supports the current consumer regime only.
    It distinguishes the right to demand delivery from the later right to
    terminate and recover money: missing delivery does not automatically mean
    an immediate refund in every case.
    """
    sources = [{"title": "TRLGDCU, art. 66 bis", "url": TRLGDCU_URL}]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    buyer_consumer = raw(facts, "purchase.buyer_is_consumer")
    seller_business = raw(facts, "purchase.seller_is_business")
    if buyer_consumer is None:
        missing.append("purchase.buyer_is_consumer")
    if seller_business is None:
        missing.append("purchase.seller_is_business")
    if buyer_consumer is False or seller_business is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=raw(facts, "purchase.amount_paid"),
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="C04 automatiza compras de una persona consumidora frente a un vendedor profesional.",
            counterarguments=[],
            missing_facts=[],
            next_action="REDIRECT_NON_CONSUMER_PURCHASE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["consumer_or_business_scope_failed"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    product = raw(facts, "purchase.product_name")
    order_date = _parse_date(raw(facts, "purchase.order_date"))
    delivered = raw(facts, "purchase.delivered")
    amount_raw = raw(facts, "purchase.amount_paid")
    amount = round(float(amount_raw), 2) if amount_raw is not None else None
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    if not product:
        missing.append("purchase.product_name")
    if not order_date:
        missing.append("purchase.order_date")
    if delivered is None:
        missing.append("purchase.delivered")
    if amount is None:
        missing.append("purchase.amount_paid")

    if order_date and order_date < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LEGACY_REVIEW",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El pedido es anterior al régimen temporal automatizado de C04. Debe revisarse la redacción aplicable en la fecha del contrato.",
            counterarguments=[],
            missing_facts=missing,
            next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY",
            failed_conditions=["order_before_2022-01-01"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if delivered is True:
        return EngineResult(
            viability="LOW",
            scope_status="REDIRECT_OTHER_PURCHASE_ISSUE",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="Con el hecho confirmado de que el pedido fue entregado, C04 (falta de entrega) deja de ser la familia correcta. Si llegó tarde, incompleto o no coincide con lo comprado debe reclasificarse.",
            counterarguments=[],
            missing_facts=[],
            next_action="RECLASSIFY_DELIVERED_ORDER",
            rule_result="FAILED",
            failed_conditions=["goods_delivered"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    agreed = raw(facts, "purchase.delivery_date_was_agreed")
    agreed_date = _parse_date(raw(facts, "purchase.agreed_delivery_date"))
    if agreed is None:
        missing.append("purchase.delivery_date_was_agreed")
    elif agreed is True and agreed_date is None:
        missing.append("purchase.agreed_delivery_date")

    due_date = None
    if order_date:
        due_date = agreed_date if agreed is True and agreed_date else order_date + timedelta(days=30)

    seller_refused = raw(facts, "purchase.seller_refused_delivery")
    essential = raw(facts, "purchase.delivery_date_essential")
    if seller_refused is None:
        missing.append("purchase.seller_refused_delivery")
    if essential is None:
        missing.append("purchase.delivery_date_essential")

    if raw(facts, "company.asserts_delivered", False):
        counterarguments.append(
            {
                "type": "SELLER_ASSERTS_DELIVERY",
                "status": "open",
                "impact": "critical",
                "origin": "company_response",
            }
        )

    burden = [
        {
            "issue": "compliance_with_delivery_obligation",
            "on": "seller",
            "basis": "TRLGDCU_66_BIS_5",
            "note": "El artículo 66 bis atribuye al empresario la carga de probar el cumplimiento de las obligaciones de entrega del artículo.",
        }
    ]

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para saber si el plazo de entrega ha vencido y si ya puede pedirse resolución o todavía corresponde exigir primero la entrega.",
            counterarguments=counterarguments,
            missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=burden,
        )

    # A clear refusal by the seller permits immediate termination even before a
    # normal additional period would otherwise be required.
    immediate_refusal = seller_refused is True
    essential_breach = bool(essential is True and due_date and analysis_date > due_date)

    if due_date and analysis_date <= due_date and not immediate_refusal:
        return EngineResult(
            viability="MEDIUM",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing=_worth(amount),
            reasoning_summary=f"La fecha de entrega aplicable todavía no ha vencido ({due_date.isoformat()}). En este momento C04 no sustenta una resolución por falta de entrega, salvo que aparezca una negativa clara del vendedor.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="WAIT_UNTIL_DELIVERY_DUE",
            rule_result="NOT_YET_DUE",
            failed_conditions=["delivery_deadline_not_expired"],
            calculation=None,
            sources=sources,
            remedies=["DELIVERY"],
            burden_of_proof=burden,
        )

    additional_requested = raw(facts, "purchase.additional_delivery_period_requested")
    additional_deadline = _parse_date(raw(facts, "purchase.additional_delivery_period_deadline"))

    can_terminate_now = immediate_refusal or essential_breach
    termination_reason = None
    if immediate_refusal:
        termination_reason = "seller_refused_delivery"
    elif essential_breach:
        termination_reason = "essential_delivery_date_breached"

    if not can_terminate_now:
        if additional_requested is None:
            return EngineResult(
                viability="HIGH",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=amount,
                worth_pursuing=_worth(amount),
                reasoning_summary="El plazo de entrega ha vencido. Como regla general, antes de resolver el contrato el consumidor debe emplazar al vendedor para que entregue en un plazo adicional adecuado a las circunstancias.",
                counterarguments=counterarguments,
                missing_facts=["purchase.additional_delivery_period_requested"],
                next_action="ASK_IF_ADDITIONAL_PERIOD_GIVEN",
                rule_result="APPLIES_DELIVERY_OVERDUE",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["DELIVERY"],
                burden_of_proof=burden,
            )
        if additional_requested is False:
            return EngineResult(
                viability="HIGH",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=amount,
                worth_pursuing=_worth(amount),
                reasoning_summary="El plazo de entrega ha vencido, pero no consta que se haya concedido todavía un plazo adicional adecuado al vendedor. El siguiente paso seguro es requerir la entrega dentro de ese plazo adicional.",
                counterarguments=counterarguments,
                missing_facts=[],
                next_action="GIVE_ADDITIONAL_DELIVERY_PERIOD",
                rule_result="APPLIES_DELIVERY_OVERDUE",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["DELIVERY"],
                burden_of_proof=burden,
            )
        if additional_deadline is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Consta que se dio un plazo adicional, pero falta saber hasta qué fecha para determinar si ya ha vencido.",
                counterarguments=counterarguments,
                missing_facts=["purchase.additional_delivery_period_deadline"],
                next_action="REQUEST_ADDITIONAL_PERIOD_DEADLINE",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["DELIVERY"],
                burden_of_proof=burden,
            )
        if analysis_date <= additional_deadline:
            return EngineResult(
                viability="HIGH",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=amount,
                worth_pursuing=_worth(amount),
                reasoning_summary=f"El vendedor está todavía dentro del plazo adicional concedido, que vence el {additional_deadline.isoformat()}. Si termina sin entrega, podrá analizarse la resolución del contrato.",
                counterarguments=counterarguments,
                missing_facts=[],
                next_action="WAIT_ADDITIONAL_DELIVERY_PERIOD",
                rule_result="ADDITIONAL_PERIOD_RUNNING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["DELIVERY"],
                burden_of_proof=burden,
            )
        can_terminate_now = True
        termination_reason = "additional_period_expired"

    open_critical = any(
        item.get("status") == "open" and item.get("impact") == "critical"
        for item in counterarguments
    )
    viability = "MEDIUM" if open_critical else "HIGH"
    calculation = {
        "type": "order_non_delivery_refund",
        "amount_paid": amount,
        "termination_reason": termination_reason,
        "delivery_due_date": due_date.isoformat() if due_date else None,
        "additional_delivery_period_deadline": additional_deadline.isoformat() if additional_deadline else None,
    }
    return EngineResult(
        viability=viability,
        scope_status="SUPPORTED",
        claimable_amount=amount,
        economic_value=amount,
        worth_pursuing=_worth(amount),
        reasoning_summary="La entrega no se ha producido y ya concurre un supuesto que permite resolver el contrato: venció el plazo adicional, el vendedor rechazó entregar o se incumplió una fecha de entrega que era esencial. Puede pedirse la resolución y la restitución del importe pagado, sin convertir una mera demora inicial en una devolución automática.",
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="PREPARE_NON_DELIVERY_TERMINATION",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["TERMINATE_CONTRACT", "REFUND_AMOUNT_PAID"],
        burden_of_proof=burden,
    )
