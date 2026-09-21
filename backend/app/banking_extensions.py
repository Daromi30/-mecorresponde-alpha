from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.b01 import evaluate_b01
from .engine.b02 import evaluate_b02

_INSTALLED = False
_PREVIOUS_SEED = svc.seed_legal


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    svc._ensure_source(
        db, "RDL19_2018", "BOE / Jefatura del Estado",
        "Real Decreto-ley 19/2018, de 23 de noviembre, de servicios de pago y otras medidas urgentes en materia financiera",
        "https://www.boe.es/eli/es/rdl/2018/11/23/19/con", date(2018, 11, 24),
    )
    rules["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"] = svc._ensure_rule(
        db, "PAYMENT_UNAUTHORIZED_REFUND_CURRENT", 1, date(2018, 11, 25), "RDL19_2018", "34, 43, 44, 45 y 46",
        {"consumer_or_microenterprise": True, "unauthorized_payment": True, "notification_article_43_scope": True},
        {"provider_refund_rule": True, "provider_evidentiary_burden": True, "thirteen_month_general_notice_limit": True, "article_46_exceptions_require_facts": True},
        "Para una operación de pago no autorizada, los artículos 43 a 46 regulan notificación, prueba, reembolso y posibles responsabilidades del ordenante. B01 automatiza solo un supuesto estrecho sin controversia material sobre fraude, negligencia grave, instrumento extraviado/sustraído o proveedor de iniciación.",
    )
    rules["PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT"] = svc._ensure_rule(
        db, "PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT", 1, date(2018, 11, 25), "RDL19_2018", "34, 48 y 49",
        {"consumer_or_microenterprise": True, "authorized_payment": True, "article_48_2_direct_debit": True, "request_within_eight_weeks": True, "article_48_4_exception_absent": True},
        {"full_refund": True, "request_period_weeks": 8, "provider_response_business_days": 10, "article_48_4_contract_exception": True},
        "B02 automatiza solo un adeudo domiciliado autorizado confirmado dentro del artículo 48.2, solicitado dentro de ocho semanas y sin posible exclusión contractual del artículo 48.4.",
    )
    return rules


def install_banking_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["B01"] = evaluate_b01
    svc.FAMILY_RULES["B01"] = ["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"]
    svc.EVALUATORS["B02"] = evaluate_b02
    svc.FAMILY_RULES["B02"] = ["PAYMENT_AUTHORIZED_DIRECT_DEBIT_REFUND_CURRENT"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
