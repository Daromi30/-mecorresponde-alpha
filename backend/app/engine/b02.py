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


def evaluate_b02(facts: dict[str, FactValue]) -> EngineResult:
    """B02 — narrow Article 48.2/49 authorized SEPA direct-debit refund route."""
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
        "bank.user_scope": scope, "bank.payer_provider_in_spain": provider_spain,
        "bank.operation_authorized": authorized, "bank.authorized_payment_type": debit_type,
        "bank.direct_debit_article_48_2_confirmed": art482, "bank.debit_date": debit_date,
        "bank.refund_request_date": request_date, "bank.article_48_4_exception_status": exception_status,
        "bank.payment_scope_clear": territorial_scope, "bank.documented_operation_amount": amount,
        "bank.refund_received": refunded,
    }
    missing = sorted(k for k, v in required.items() if v is None)
    if missing:
        return EngineResult("INSUFFICIENT_INFORMATION", "SUPPORTED", None, amount, "NEEDS_INFORMATION",
            "Faltan hechos esenciales para aplicar de forma segura la devolución de un adeudo domiciliado autorizado.", [], missing,
            "REQUEST_MATERIAL_FACT", "PENDING", [], None, sources, [], [])
    if scope not in {"consumer", "microenterprise"}:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "El artículo 34 permite pactos distintos para determinados usuarios no consumidores ni microempresas.", [], [],
            "HUMAN_REVIEW_B02_NON_CONSUMER_SCOPE", "MANUAL_REVIEW", [], None, sources, [], [])
    if provider_spain is not True or territorial_scope is not True:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "El ámbito territorial o del proveedor no está suficientemente confirmado para automatizar B02.", [], [],
            "HUMAN_REVIEW_B02_SCOPE", "MANUAL_REVIEW", [], None, sources, [], [])
    if authorized is False:
        return EngineResult("OUT_OF_SCOPE", "UNSUPPORTED", None, amount, "NEEDS_REANALYSIS",
            "La operación no autorizada pertenece a B01 y no al régimen de devolución de operaciones autorizadas de los artículos 48 y 49.", [], [],
            "RECLASSIFY_B01_UNAUTHORIZED_PAYMENT", "NOT_APPLICABLE", ["authorized_operation_required"], None, sources, [], [])
    if debit_type != "direct_debit" or art482 is not True:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "B02 solo automatiza adeudos domiciliados confirmados dentro del artículo 48.2; otros pagos iniciados por beneficiario requieren análisis del artículo 48.1.", [], [],
            "HUMAN_REVIEW_B02_ARTICLE_48_SCOPE", "MANUAL_REVIEW", [], None, sources, [], [])
    assert debit_date is not None and request_date is not None
    if request_date < debit_date:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "La fecha de solicitud es anterior al adeudo y los hechos son inconsistentes.", [], [],
            "HUMAN_REVIEW_B02_DATE_INCONSISTENCY", "MANUAL_REVIEW", [], None, sources, [], [])
    deadline = debit_date + timedelta(weeks=8)
    if request_date > deadline:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "La solicitud indicada supera las ocho semanas del artículo 49.1; B02 no crea automáticamente otro derecho de devolución.", [], [],
            "HUMAN_REVIEW_B02_OUTSIDE_EIGHT_WEEKS", "MANUAL_REVIEW", [], {"deadline": deadline.isoformat()}, sources, [], [])
    if exception_status != "clearly_absent":
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "Existe o puede existir una exclusión contractual del artículo 48.4 y debe revisarse el contrato y el aviso previo.", [], [],
            "HUMAN_REVIEW_B02_ARTICLE_48_4", "MANUAL_REVIEW", [], None, sources, [], [])
    assert amount is not None
    if amount <= 0:
        return EngineResult("PROFESSIONAL_REVIEW", "LIMITED_SCOPE", None, amount, "PROFESSIONAL_REVIEW",
            "El importe documentado no permite cuantificar la devolución.", [], [], "HUMAN_REVIEW_B02_INVALID_AMOUNT", "MANUAL_REVIEW", [], None, sources, [], [])
    received = 0.0
    if refunded is True:
        received_amount = _money(raw(facts, "bank.refund_received_amount"))
        if received_amount is None:
            return EngineResult("INSUFFICIENT_INFORMATION", "SUPPORTED", None, amount, "NEEDS_INFORMATION",
                "Falta el importe ya devuelto.", [], ["bank.refund_received_amount"], "REQUEST_MATERIAL_FACT", "PENDING", [], None, sources, [], [])
        received = max(received_amount, 0.0)
    outstanding = round(max(amount - received, 0.0), 2)
    calculation = {"documented_amount": amount, "already_refunded": received, "outstanding_refund": outstanding,
                   "eight_week_deadline": deadline.isoformat(), "provider_response_business_days": 10}
    if outstanding <= 0:
        return EngineResult("LOW", "SUPPORTED", 0.0, amount, "NO_PAID_MANAGEMENT", "La devolución acreditada ya cubre el adeudo documentado.", [], [],
            "EXPLAIN_B02_ALREADY_REFUNDED", "APPLIES", [], calculation, sources, ["VERIFY_AUTHORIZED_DIRECT_DEBIT_REFUND_PAID"], [])
    return EngineResult("HIGH", "SUPPORTED", outstanding, amount, "YES" if outstanding >= 50 else "YES_IF_LOW_COST",
        "El adeudo domiciliado autorizado está confirmado dentro del artículo 48.2, la solicitud se formula dentro de ocho semanas y no consta una excepción contractual aplicable del artículo 48.4.", [], [],
        "PREPARE_B02_AUTHORIZED_DIRECT_DEBIT_REFUND", "APPLIES", [], calculation, sources, ["AUTHORIZED_DIRECT_DEBIT_REFUND"], [])
