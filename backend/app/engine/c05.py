from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .common import EngineResult, FactValue, raw

TRLGDCU_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555"
CURRENT_REGIME_START = date(2022, 5, 28)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + 1)


def _worth(amount: float | None) -> str:
    if amount is None:
        return "NEEDS_INFORMATION"
    if amount < 30:
        return "YES_IF_LOW_COST"
    return "YES"


def evaluate_c05(facts: dict[str, FactValue]) -> EngineResult:
    """C05 — withdrawal from an ordinary distance sale of physical goods.

    This first automated slice deliberately excludes cases where an Article 103
    exception may apply. It also separates exercising withdrawal, returning the
    goods and the seller's refund deadline instead of treating all three as one
    event.
    """
    sources = [
        {
            "title": "TRLGDCU, arts. 102-108",
            "url": TRLGDCU_URL,
        }
    ]
    missing: list[str] = []
    counterarguments: list[dict[str, Any]] = []

    buyer_consumer = raw(facts, "purchase.buyer_is_consumer")
    seller_business = raw(facts, "purchase.seller_is_business")
    distance_contract = raw(facts, "purchase.distance_contract")
    if buyer_consumer is None:
        missing.append("purchase.buyer_is_consumer")
    if seller_business is None:
        missing.append("purchase.seller_is_business")
    if distance_contract is None:
        missing.append("purchase.distance_contract")

    if buyer_consumer is False or seller_business is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=raw(facts, "purchase.amount_paid"),
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="C05 automatiza el desistimiento de una persona consumidora frente a un vendedor profesional.",
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
    if distance_contract is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="REDIRECT_OTHER_PURCHASE_ISSUE",
            claimable_amount=None,
            economic_value=raw(facts, "purchase.amount_paid"),
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="C05 está limitado en esta alpha a contratos celebrados a distancia. Una compra presencial necesita otro análisis.",
            counterarguments=[],
            missing_facts=[],
            next_action="RECLASSIFY_NON_DISTANCE_PURCHASE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["not_distance_contract"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    product = raw(facts, "purchase.product_name")
    received = _parse_date(raw(facts, "purchase.received_date"))
    amount_raw = raw(facts, "purchase.amount_paid")
    amount = round(float(amount_raw), 2) if amount_raw is not None else None
    premium_raw = raw(facts, "purchase.premium_delivery_extra")
    premium_extra = round(float(premium_raw), 2) if premium_raw is not None else None
    analysis_date = _parse_date(raw(facts, "system.analysis_date")) or date.today()

    if not product:
        missing.append("purchase.product_name")
    if received is None:
        missing.append("purchase.received_date")
    if amount is None:
        missing.append("purchase.amount_paid")
    if premium_extra is None:
        missing.append("purchase.premium_delivery_extra")

    if received and received < CURRENT_REGIME_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LEGACY_REVIEW",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La recepción del bien es anterior al régimen temporal automatizado de C05. Debe revisarse la redacción histórica aplicable.",
            counterarguments=[],
            missing_facts=missing,
            next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY",
            failed_conditions=["receipt_before_2022-05-28"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    possible_exception = raw(facts, "purchase.withdrawal_exception_possible")
    if possible_exception is None:
        missing.append("purchase.withdrawal_exception_possible")
    elif possible_exception is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Hay indicios de que puede concurrir una excepción legal al derecho de desistimiento del artículo 103. Esta alpha no decide automáticamente una excepción sin revisión jurídica específica.",
            counterarguments=[
                {
                    "type": "POSSIBLE_WITHDRAWAL_EXCEPTION",
                    "status": "confirmed",
                    "impact": "critical",
                }
            ],
            missing_facts=[],
            next_action="HUMAN_REVIEW_WITHDRAWAL_EXCEPTION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    informed = raw(facts, "purchase.withdrawal_information_provided")
    if informed is None:
        missing.append("purchase.withdrawal_information_provided")
    later_info = _parse_date(raw(facts, "purchase.withdrawal_information_later_date"))

    withdrawal_sent = raw(facts, "purchase.withdrawal_sent")
    if withdrawal_sent is None:
        missing.append("purchase.withdrawal_sent")
    sent_date = _parse_date(raw(facts, "purchase.withdrawal_sent_date"))
    if withdrawal_sent is True and sent_date is None:
        missing.append("purchase.withdrawal_sent_date")

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos necesarios para calcular el plazo de desistimiento y determinar si ya fue ejercitado correctamente.",
            counterarguments=counterarguments,
            missing_facts=sorted(set(missing)),
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert received is not None
    ordinary_deadline = received + timedelta(days=14)
    if informed is True:
        withdrawal_deadline = ordinary_deadline
        deadline_basis = "ordinary_14_days"
    elif later_info:
        extended_outer_limit = _add_year(ordinary_deadline)
        if later_info > extended_outer_limit:
            withdrawal_deadline = extended_outer_limit
            deadline_basis = "missing_information_12_month_extension"
        else:
            withdrawal_deadline = later_info + timedelta(days=14)
            deadline_basis = "late_information_plus_14_days"
    else:
        withdrawal_deadline = _add_year(ordinary_deadline)
        deadline_basis = "missing_information_12_month_extension"

    consumer_burden = [
        {
            "issue": "withdrawal_exercised_in_time",
            "on": "consumer",
            "basis": "TRLGDCU_106_4",
            "note": "La carga de probar el ejercicio del desistimiento recae en el consumidor.",
        }
    ]

    if withdrawal_sent is False:
        if analysis_date > withdrawal_deadline:
            return EngineResult(
                viability="LOW",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=amount,
                worth_pursuing="NO_PAID_MANAGEMENT",
                reasoning_summary="Con los hechos actuales no consta que se ejercitara el desistimiento antes de vencer el plazo aplicable. C05 no sustenta ahora una devolución por desistimiento, sin perjuicio de que exista otra causa de reclamación.",
                counterarguments=counterarguments,
                missing_facts=[],
                next_action="EXPLAIN_WITHDRAWAL_PERIOD_EXPIRED",
                rule_result="FAILED",
                failed_conditions=["withdrawal_not_exercised_in_time"],
                calculation={
                    "type": "withdrawal_deadline",
                    "deadline": withdrawal_deadline.isoformat(),
                    "basis": deadline_basis,
                },
                sources=sources,
                remedies=[],
                burden_of_proof=consumer_burden,
            )
        return EngineResult(
            viability="HIGH",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing=_worth(amount),
            reasoning_summary=f"El desistimiento todavía puede ejercitarse dentro del plazo aplicable, que con los hechos actuales finaliza el {withdrawal_deadline.isoformat()}. Debe comunicarse al vendedor mediante una declaración inequívoca antes de que venza.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="SEND_WITHDRAWAL_NOTICE",
            rule_result="APPLIES_RIGHT_AVAILABLE",
            failed_conditions=[],
            calculation={
                "type": "withdrawal_deadline",
                "deadline": withdrawal_deadline.isoformat(),
                "basis": deadline_basis,
            },
            sources=sources,
            remedies=["WITHDRAWAL", "REFUND_AFTER_VALID_WITHDRAWAL"],
            burden_of_proof=consumer_burden,
        )

    assert sent_date is not None
    if sent_date > withdrawal_deadline:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La comunicación de desistimiento se envió después del plazo aplicable según los hechos confirmados. C05 no sustenta el reembolso por desistimiento con esta cronología.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="EXPLAIN_LATE_WITHDRAWAL",
            rule_result="FAILED",
            failed_conditions=["withdrawal_sent_after_deadline"],
            calculation={
                "type": "withdrawal_deadline",
                "deadline": withdrawal_deadline.isoformat(),
                "sent_date": sent_date.isoformat(),
                "basis": deadline_basis,
            },
            sources=sources,
            remedies=[],
            burden_of_proof=consumer_burden,
        )

    refund_received = raw(facts, "purchase.refund_received")
    if refund_received is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="El desistimiento parece haberse comunicado a tiempo, pero falta saber si el vendedor ya ha efectuado el reembolso.",
            counterarguments=counterarguments,
            missing_facts=["purchase.refund_received"],
            next_action="ASK_REFUND_STATUS",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=["REFUND"],
            burden_of_proof=consumer_burden,
        )

    refundable = round(max(0.0, float(amount or 0.0) - float(premium_extra or 0.0)), 2)
    refund_received_amount_raw = raw(facts, "purchase.refund_received_amount", 0.0) or 0.0
    refund_received_amount = round(float(refund_received_amount_raw), 2)
    outstanding = round(max(0.0, refundable - refund_received_amount), 2)

    if refund_received is True and outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_FURTHER_ACTION",
            reasoning_summary="El desistimiento fue ejercitado dentro de plazo y consta el reembolso del importe calculado en esta alpha. No queda una cantidad pendiente por C05.",
            counterarguments=[],
            missing_facts=[],
            next_action="VERIFY_AND_CLOSE_WITHDRAWAL",
            rule_result="SATISFIED",
            failed_conditions=[],
            calculation={
                "type": "withdrawal_refund",
                "refundable_amount": refundable,
                "received_amount": refund_received_amount,
                "outstanding": 0.0,
            },
            sources=sources,
            remedies=[],
            burden_of_proof=consumer_burden,
        )

    seller_collects = raw(facts, "purchase.seller_offered_collection")
    return_sent = raw(facts, "purchase.return_sent")
    return_proof = raw(facts, "purchase.return_proof_available")
    if seller_collects is None:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Para saber si el vendedor puede retener temporalmente el reembolso falta saber si se ofreció a recoger el bien.",
            counterarguments=counterarguments,
            missing_facts=["purchase.seller_offered_collection"],
            next_action="ASK_RETURN_LOGISTICS",
            rule_result="PENDING",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=["REFUND"],
            burden_of_proof=consumer_burden,
        )

    if seller_collects is False:
        if return_sent is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="El vendedor no se ofreció a recoger el bien. Falta saber si ya se devolvió para valorar si puede retener el reembolso hasta recibirlo o ver una prueba de devolución.",
                counterarguments=counterarguments,
                missing_facts=["purchase.return_sent"],
                next_action="ASK_RETURN_STATUS",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["RETURN_GOODS", "REFUND"],
                burden_of_proof=consumer_burden,
            )
        if return_sent is False:
            return EngineResult(
                viability="HIGH",
                scope_status="SUPPORTED",
                claimable_amount=0.0,
                economic_value=amount,
                worth_pursuing=_worth(amount),
                reasoning_summary="El desistimiento se ejercitó a tiempo, pero el bien todavía no se ha devuelto y el vendedor no se ofreció a recogerlo. El empresario puede retener el reembolso hasta recibir el bien o una prueba de su devolución.",
                counterarguments=[
                    {
                        "type": "SELLER_MAY_WITHHOLD_PENDING_RETURN",
                        "status": "confirmed",
                        "impact": "material",
                    }
                ],
                missing_facts=[],
                next_action="RETURN_GOODS_WITH_PROOF",
                rule_result="APPLIES_RETURN_PENDING",
                failed_conditions=[],
                calculation={
                    "type": "withdrawal_refund",
                    "refundable_amount": refundable,
                    "outstanding": outstanding,
                },
                sources=sources,
                remedies=["RETURN_GOODS", "REFUND"],
                burden_of_proof=consumer_burden,
            )
        if return_proof is None:
            return EngineResult(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Consta que el bien se devolvió, pero falta confirmar si existe prueba de devolución para neutralizar una posible retención del reembolso.",
                counterarguments=counterarguments,
                missing_facts=["purchase.return_proof_available"],
                next_action="CONFIRM_RETURN_PROOF",
                rule_result="PENDING",
                failed_conditions=[],
                calculation=None,
                sources=sources,
                remedies=["REFUND"],
                burden_of_proof=consumer_burden,
            )
        if return_proof is False:
            counterarguments.append(
                {
                    "type": "RETURN_PROOF_MISSING",
                    "status": "confirmed",
                    "impact": "material",
                }
            )

    refund_due_date = sent_date + timedelta(days=14)
    if raw(facts, "company.asserts_withdrawal_late", False):
        counterarguments.append(
            {
                "type": "SELLER_ASSERTS_WITHDRAWAL_LATE",
                "status": "open",
                "impact": "material",
                "origin": "company_response",
            }
        )
    if raw(facts, "company.asserts_withdrawal_exception", False):
        counterarguments.append(
            {
                "type": "SELLER_ASSERTS_WITHDRAWAL_EXCEPTION",
                "status": "open",
                "impact": "critical",
                "origin": "company_response",
            }
        )

    if analysis_date <= refund_due_date:
        return EngineResult(
            viability="HIGH",
            scope_status="SUPPORTED",
            claimable_amount=outstanding,
            economic_value=amount,
            worth_pursuing=_worth(amount),
            reasoning_summary=f"El desistimiento fue comunicado dentro de plazo. El empresario dispone, como máximo general, de 14 días naturales desde la comunicación para efectuar el reembolso, con la posibilidad de retención por devolución prevista en el artículo 107.3. El plazo calculado vence el {refund_due_date.isoformat()}.",
            counterarguments=counterarguments,
            missing_facts=[],
            next_action="WAIT_WITHDRAWAL_REFUND_PERIOD",
            rule_result="REFUND_PERIOD_RUNNING",
            failed_conditions=[],
            calculation={
                "type": "withdrawal_refund",
                "refundable_amount": refundable,
                "received_amount": refund_received_amount,
                "outstanding": outstanding,
                "refund_due_date": refund_due_date.isoformat(),
            },
            sources=sources,
            remedies=["REFUND"],
            burden_of_proof=consumer_burden,
        )

    open_critical = any(
        item.get("status") == "open" and item.get("impact") == "critical"
        for item in counterarguments
    )
    viability = "MEDIUM" if open_critical else "HIGH"
    return EngineResult(
        viability=viability,
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=amount,
        worth_pursuing=_worth(amount),
        reasoning_summary="El desistimiento fue ejercitado dentro del plazo calculado y el plazo general de 14 días para el reembolso ya ha transcurrido. Si el vendedor no puede ampararse en la retención por devolución del bien, procede reclamar la cantidad pendiente.",
        counterarguments=counterarguments,
        missing_facts=[],
        next_action="PREPARE_WITHDRAWAL_REFUND_CLAIM",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation={
            "type": "withdrawal_refund",
            "refundable_amount": refundable,
            "received_amount": refund_received_amount,
            "outstanding": outstanding,
            "refund_due_date": refund_due_date.isoformat(),
            "withdrawal_deadline": withdrawal_deadline.isoformat(),
            "withdrawal_deadline_basis": deadline_basis,
        },
        sources=sources,
        remedies=["REFUND"],
        burden_of_proof=consumer_burden,
    )
