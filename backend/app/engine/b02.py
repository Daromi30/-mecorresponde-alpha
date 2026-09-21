from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .common import EngineResult, FactValue, raw

RDL19_URL = "https://www.boe.es/eli/es/rdl/2018/11/23/19/con"


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


def _result(
    *,
    viability: str,
    scope_status: str,
    claimable_amount: float | None,
    economic_value: float | None,
    worth_pursuing: str,
    reasoning_summary: str,
    missing_facts: list[str],
    next_action: str,
    rule_result: str,
    sources: list[dict[str, str]],
    failed_conditions: list[str] | None = None,
    calculation: dict[str, Any] | None = None,
    remedies: list[str] | None = None,
) -> EngineResult:
    return EngineResult(
        viability=viability,
        scope_status=scope_status,
        claimable_amount=claimable_amount,
        economic_value=economic_value,
        worth_pursuing=worth_pursuing,
        reasoning_summary=reasoning_summary,
        counterarguments=[],
        missing_facts=missing_facts,
        next_action=next_action,
        rule_result=rule_result,
        failed_conditions=failed_conditions or [],
        calculation=calculation,
        sources=sources,
        remedies=remedies or [],
        burden_of_proof=[],
    )


def evaluate_b02(facts: dict[str, FactValue]) -> EngineResult:
    """B02 — narrow Article 48.2/49 authorized direct-debit refund route."""
    sources = [{"title": "Real Decreto-ley 19/2018, arts. 34, 48 y 49", "url": RDL19_URL}]

    scope = raw(facts, "bank.user_scope")
    provider_spain = raw(facts, "bank.payer_provider_in_spain")
    authorized = raw(facts, "bank.operation_authorized")
    debit_type = raw(facts, "bank.authorized_payment_type")
    art482 = raw(facts, "bank.direct_debit_article_48_2_confirmed")
    debit_date = _date(raw(facts, "bank.debit_date"))
    request_date = _date(raw(facts, "bank.refund_request_date"))
    exception_status = raw(facts, "bank.article_48_4_exception_status")
    territorial_scope = raw(facts, "bank.payment_scope_clear")
    amount = _money(raw(facts, "bank.documented_operation_amount"))
    refunded = raw(facts, "bank.refund_received")

    required = {
        "bank.user_scope": scope,
        "bank.payer_provider_in_spain": provider_spain,
        "bank.operation_authorized": authorized,
        "bank.authorized_payment_type": debit_type,
        "bank.direct_debit_article_48_2_confirmed": art482,
        "bank.debit_date": debit_date,
        "bank.refund_request_date": request_date,
        "bank.article_48_4_exception_status": exception_status,
        "bank.payment_scope_clear": territorial_scope,
        "bank.documented_operation_amount": amount,
        "bank.refund_received": refunded,
    }
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        return _result(
            viability="INSUFFICIENT_INFORMATION",
            scope_status="SUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary=(
                "Faltan hechos esenciales para aplicar de forma segura la devolución de un adeudo domiciliado autorizado."
            ),
            missing_facts=missing,
            next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING",
            sources=sources,
        )

    if scope not in {"consumer", "microenterprise"}:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "El artículo 34 permite pactos distintos para determinados usuarios que no sean consumidores ni microempresas."
            ),
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_NON_CONSUMER_SCOPE",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    if provider_spain is not True or territorial_scope is not True:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El ámbito territorial o del proveedor no está suficientemente confirmado para automatizar B02.",
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_SCOPE",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    if authorized is False:
        return _result(
            viability="OUT_OF_SCOPE",
            scope_status="UNSUPPORTED",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary=(
                "La operación no autorizada pertenece a B01 y no al régimen de devolución de operaciones autorizadas de los artículos 48 y 49."
            ),
            missing_facts=[],
            next_action="RECLASSIFY_B01_UNAUTHORIZED_PAYMENT",
            rule_result="NOT_APPLICABLE",
            sources=sources,
            failed_conditions=["authorized_operation_required"],
        )

    if debit_type != "direct_debit" or art482 is not True:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "B02 solo automatiza adeudos domiciliados confirmados dentro del artículo 48.2; otros pagos iniciados por beneficiario requieren analizar el artículo 48.1."
            ),
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_ARTICLE_48_SCOPE",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    assert debit_date is not None and request_date is not None
    if request_date < debit_date:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La fecha de solicitud es anterior al adeudo y los hechos son inconsistentes.",
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_DATE_INCONSISTENCY",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    deadline = debit_date + timedelta(weeks=8)
    if request_date > deadline:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "La solicitud indicada supera las ocho semanas del artículo 49.1; B02 no crea automáticamente otro derecho de devolución."
            ),
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_OUTSIDE_EIGHT_WEEKS",
            rule_result="MANUAL_REVIEW",
            sources=sources,
            calculation={"eight_week_deadline": deadline.isoformat()},
        )

    if exception_status != "clearly_absent":
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary=(
                "Existe o puede existir una exclusión contractual del artículo 48.4 y debe revisarse el contrato, el consentimiento y el aviso previo."
            ),
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_ARTICLE_48_4",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    assert amount is not None
    if amount <= 0:
        return _result(
            viability="PROFESSIONAL_REVIEW",
            scope_status="LIMITED_SCOPE",
            claimable_amount=None,
            economic_value=amount,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="El importe documentado no permite cuantificar la devolución.",
            missing_facts=[],
            next_action="HUMAN_REVIEW_B02_INVALID_AMOUNT",
            rule_result="MANUAL_REVIEW",
            sources=sources,
        )

    received = 0.0
    if refunded is True:
        received_amount = _money(raw(facts, "bank.refund_received_amount"))
        if received_amount is None:
            return _result(
                viability="INSUFFICIENT_INFORMATION",
                scope_status="SUPPORTED",
                claimable_amount=None,
                economic_value=amount,
                worth_pursuing="NEEDS_INFORMATION",
                reasoning_summary="Falta el importe ya devuelto.",
                missing_facts=["bank.refund_received_amount"],
                next_action="REQUEST_MATERIAL_FACT",
                rule_result="PENDING",
                sources=sources,
            )
        received = max(received_amount, 0.0)

    outstanding = round(max(amount - received, 0.0), 2)
    calculation = {
        "documented_amount": amount,
        "already_refunded": round(received, 2),
        "outstanding_refund": outstanding,
        "eight_week_deadline": deadline.isoformat(),
        "provider_response_business_days": 10,
    }

    if outstanding <= 0:
        return _result(
            viability="LOW",
            scope_status="SUPPORTED",
            claimable_amount=0.0,
            economic_value=amount,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="La devolución acreditada ya cubre el adeudo documentado.",
            missing_facts=[],
            next_action="EXPLAIN_B02_ALREADY_REFUNDED",
            rule_result="APPLIES",
            sources=sources,
            calculation=calculation,
            remedies=["VERIFY_AUTHORIZED_DIRECT_DEBIT_REFUND_PAID"],
        )

    return _result(
        viability="HIGH",
        scope_status="SUPPORTED",
        claimable_amount=outstanding,
        economic_value=amount,
        worth_pursuing="YES" if outstanding >= 50 else "YES_IF_LOW_COST",
        reasoning_summary=(
            "El adeudo domiciliado autorizado está confirmado dentro del artículo 48.2, la solicitud se formula dentro de ocho semanas y no consta una excepción contractual aplicable del artículo 48.4."
        ),
        missing_facts=[],
        next_action="PREPARE_B02_AUTHORIZED_DIRECT_DEBIT_REFUND",
        rule_result="APPLIES",
        sources=sources,
        calculation=calculation,
        remedies=["AUTHORIZED_DIRECT_DEBIT_REFUND"],
    )
