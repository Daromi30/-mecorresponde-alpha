from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from .common import EngineResult, FactValue, raw

RDL19_URL = "https://www.boe.es/eli/es/rdl/2018/11/23/19/con"


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


def _plus_months(value: date, months: int) -> date:
    month0 = value.month - 1 + months
    year = value.year + month0 // 12
    month = month0 % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_b01(facts: dict[str, FactValue]) -> EngineResult:
    """B01 — narrow prima-facie refund route for an unauthorized payment.

    The evaluator never decides fraud, gross negligence or disputed authentication.
    Those issues are evidentiary/legal questions and fail closed to human review.
    The automated route also excludes lost/stolen/misappropriated instruments because
    Article 46 can allocate up to EUR 50 or create other exceptions.
    """
    sources = [{
        "title": "Real Decreto-ley 19/2018, arts. 34 y 43 a 46",
        "url": RDL19_URL,
    }]

    user_scope = raw(facts, "bank.user_scope")
    provider_in_spain = raw(facts, "bank.payer_provider_in_spain")
    unauthorized = raw(facts, "bank.operation_unauthorized")
    debit_date = _parse_date(raw(facts, "bank.debit_date"))
    awareness_date = _parse_date(raw(facts, "bank.awareness_date"))
    notification_date = _parse_date(raw(facts, "bank.notification_date"))
    provider_supplied_info = raw(facts, "bank.provider_supplied_operation_info")
    pisp = raw(facts, "bank.payment_initiation_provider_involved")
    instrument_status = raw(facts, "bank.instrument_status")
    fraud_or_gross_negligence = raw(facts, "bank.provider_alleges_fraud_or_gross_negligence")
    fraud_suspicion = raw(facts, "bank.provider_fraud_suspicion_status")

    missing: list[str] = []
    for key, value in [
        ("bank.user_scope", user_scope),
        ("bank.payer_provider_in_spain", provider_in_spain),
        ("bank.operation_unauthorized", unauthorized),
        ("bank.debit_date", debit_date),
        ("bank.awareness_date", awareness_date),
        ("bank.notification_date", notification_date),
        ("bank.provider_supplied_operation_info", provider_supplied_info),
        ("bank.payment_initiation_provider_involved", pisp),
        ("bank.instrument_status", instrument_status),
        ("bank.provider_alleges_fraud_or_gross_negligence", fraud_or_gross_negligence),
        ("bank.provider_fraud_suspicion_status", fraud_suspicion),
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
            reasoning_summary="Faltan hechos esenciales para aplicar de forma segura la ruta B01 de operación no autorizada.",
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

    if user_scope not in {"consumer", "microenterprise"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 34 permite que ciertos usuarios que no sean consumidores ni microempresas pacten "
                "la inaplicación de algunas reglas del título III. B01 no presume ese régimen contractual."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_NON_CONSUMER_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if provider_in_spain is False:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="B01 automatiza solo supuestos con el proveedor de servicios de pago del ordenante situado en España.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_TERRITORIAL_SCOPE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )
    if unauthorized is False:
        return EngineResult(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "B01 solo cubre operaciones que el ordenante niega haber autorizado. Las devoluciones de operaciones "
                "autorizadas iniciadas por beneficiarios tienen reglas distintas en los artículos 48 y 49."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_B01_AUTHORIZED_OPERATION_OTHER_ROUTE",
            rule_result="NOT_APPLICABLE",
            failed_conditions=["unauthorized_operation_required"],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    assert debit_date is not None and awareness_date is not None and notification_date is not None
    if awareness_date < debit_date or notification_date < awareness_date:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="Las fechas de adeudo, conocimiento o comunicación no son coherentes y requieren revisión.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    thirteen_month_deadline = _plus_months(debit_date, 13)
    if notification_date > thirteen_month_deadline:
        if provider_supplied_info is False:
            return EngineResult(
                viability="PROFESSIONAL_REVIEW",
                scope_status="LIMITED_SCOPE",
                claimable_amount=None,
                economic_value=None,
                worth_pursuing="PROFESSIONAL_REVIEW",
                reasoning_summary=(
                    "La comunicación supera trece meses, pero el artículo 43 exceptúa esos plazos cuando el proveedor "
                    "no facilitó o puso a disposición la información de la operación. B01 no decide automáticamente esa excepción."
                ),
                counterarguments=[],
                missing_facts=[],
                next_action="HUMAN_REVIEW_B01_13_MONTH_INFORMATION_EXCEPTION",
                rule_result="MANUAL_REVIEW",
                failed_conditions=[],
                calculation={"article_43_deadline": thirteen_month_deadline.isoformat()},
                sources=sources,
                remedies=[],
                burden_of_proof=[],
            )
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La comunicación confirmada supera el máximo general de trece meses del artículo 43. "
                "B01 no descarta otras vías, pero no genera automáticamente esta solicitud de reembolso."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_OUTSIDE_13_MONTHS",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={"article_43_deadline": thirteen_month_deadline.isoformat()},
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    # The statute uses the evaluative phrase 'sin demora injustificada'. B01 only
    # automates the obviously prompt case and refuses to invent a universal day limit.
    if notification_date > awareness_date + timedelta(days=1):
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 43 exige comunicar sin demora injustificada. Como la comunicación no fue el mismo día "
                "ni el siguiente, B01 no convierte un número de días en una conclusión jurídica automática."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_NOTIFICATION_PROMPTNESS",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation={
                "awareness_date": awareness_date.isoformat(),
                "notification_date": notification_date.isoformat(),
                "article_43_deadline": thirteen_month_deadline.isoformat(),
            },
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if pisp is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Cuando interviene un proveedor de iniciación de pagos, los artículos 43.2, 44 y 45.2 distribuyen "
                "obligaciones probatorias y de reembolso entre proveedores. B01 no automatiza todavía esa concurrencia."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_PISP",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if instrument_status != "not_lost_stolen_or_misappropriated":
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 46 contiene reglas específicas para instrumentos extraviados, sustraídos o apropiados "
                "indebidamente, incluido un posible tramo de hasta 50 euros y varias excepciones. B01 no fija ese reparto automáticamente."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_ARTICLE_46_INSTRUMENT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    if fraud_or_gross_negligence is True:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 46 puede trasladar pérdidas al ordenante en caso de fraude o incumplimiento deliberado/negligencia grave, "
                "pero el artículo 44 atribuye al proveedor la carga de probar esos extremos. B01 no decide esta controversia automáticamente."
            ),
            counterarguments=["El proveedor afirma fraude o negligencia grave y debe aportar prueba suficiente conforme al artículo 44."],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_FRAUD_OR_GROSS_NEGLIGENCE",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=["PROVIDER_MUST_PROVE_FRAUD_OR_GROSS_NEGLIGENCE"],
        )

    if fraud_suspicion in {"reported_to_bde", "unknown"}:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 45 permite retrasar la devolución inmediata si existen motivos razonables para sospechar fraude "
                "y el proveedor los comunica por escrito al Banco de España. Ese supuesto requiere verificación humana."
            ),
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_PROVIDER_FRAUD_SUSPICION",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    amount = _money(raw(facts, "bank.documented_operation_amount"))
    refunded = raw(facts, "bank.refund_received")
    missing_money: list[str] = []
    if amount is None:
        missing_money.append("bank.documented_operation_amount")
    if refunded is None:
        missing_money.append("bank.refund_received")
    received_amount = 0.0
    if refunded is True:
        received = _money(raw(facts, "bank.refund_received_amount"))
        if received is None:
            missing_money.append("bank.refund_received_amount")
        else:
            received_amount = max(received, 0.0)

    if missing_money:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Falta el importe documentado de la operación o del reembolso recibido para cuantificar el saldo.",
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

    assert amount is not None
    if amount <= 0:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El importe documentado no permite cuantificar una devolución monetaria fiable.",
            counterarguments=[],
            missing_facts=[],
            next_action="HUMAN_REVIEW_B01_INVALID_AMOUNT",
            rule_result="MANUAL_REVIEW",
            failed_conditions=[],
            calculation=None,
            sources=sources,
            remedies=[],
            burden_of_proof=[],
        )

    outstanding = round(max(amount - received_amount, 0.0), 2)
    calculation = {
        "type": "unauthorized_payment_refund",
        "documented_operation_amount": amount,
        "already_refunded": round(received_amount, 2),
        "outstanding_refund": outstanding,
        "article_43_deadline": thirteen_month_deadline.isoformat(),
        "notification_days_after_awareness": (notification_date - awareness_date).days,
        "article_46_loss_allocation_automated": False,
    }

    if outstanding <= 0:
        return EngineResult(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="El reembolso acreditado ya cubre el importe documentado de la operación no autorizada.",
            counterarguments=[],
            missing_facts=[],
            next_action="EXPLAIN_B01_ALREADY_REFUNDED",
            rule_result="APPLIES",
            failed_conditions=[],
            calculation=calculation,
            sources=sources,
            remedies=["VERIFY_UNAUTHORIZED_PAYMENT_ALREADY_REFUNDED"],
            burden_of_proof=["PROVIDER_AUTHENTICATION_AND_AUTHORIZATION_EVIDENCE"],
        )

    return EngineResult(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=amount,
        worth_pursuing="YES_IF_LOW_COST" if outstanding < 50 else "YES",
        reasoning_summary=(
            "En este alcance estrecho, el ordenante niega haber autorizado la operación, comunicó de forma inmediatamente "
            "verificable y dentro del plazo general del artículo 43, y no consta una excepción del artículo 46 que B01 pueda "
            "aplicar automáticamente. El artículo 45 establece el reembolso de la operación no autorizada; el artículo 44 "
            "mantiene en el proveedor la carga probatoria sobre autenticación y, en su caso, fraude o negligencia grave."
        ),
        counterarguments=[],
        missing_facts=[],
        next_action="PREPARE_B01_UNAUTHORIZED_PAYMENT_REFUND",
        rule_result="APPLIES",
        failed_conditions=[],
        calculation=calculation,
        sources=sources,
        remedies=["REFUND_UNAUTHORIZED_PAYMENT_AND_RESTORE_ACCOUNT"],
        burden_of_proof=[
            "PROVIDER_MUST_PROVE_AUTHENTICATION_AND_CORRECT_RECORDING",
            "PROVIDER_MUST_PROVE_FRAUD_OR_GROSS_NEGLIGENCE_IF_ALLEGED",
        ],
    )
