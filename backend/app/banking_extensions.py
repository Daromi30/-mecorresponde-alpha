from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session
from . import services_v2 as svc
from .engine.b01 import evaluate_b01

_INSTALLED = False
_PREVIOUS_SEED = svc.seed_legal


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    svc._ensure_source(db, "BOE_RDL19_2018", "Boletín Oficial del Estado", "Real Decreto-ley 19/2018, de servicios de pago", "https://www.boe.es/eli/es/rdl/2018/11/23/19/con", date(2018, 11, 24))
    rules["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"] = svc._ensure_rule(
        db, "PAYMENT_UNAUTHORIZED_REFUND_CURRENT", 1, date(2018, 11, 24), "BOE_RDL19_2018", "34, 43, 44, 45, 46",
        {"user_scope": ["consumer", "microenterprise"], "unauthorized_payment": True, "general_notification_limit_months": 13, "fail_closed_on_authentication_or_fraud_dispute": True},
        {"refund": True, "possible_payer_share_max_eur": 50, "provider_fraud_suspicion_exception_requires_review": True},
        "Ruta estrecha para operaciones de pago no autorizadas: plazo del artículo 43, carga probatoria del 44, reembolso del 45 y responsabilidad limitada del 46. Fraude, negligencia grave, autenticación controvertida y excepciones se remiten a revisión humana."
    )
    return rules


def install_banking_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["B01"] = evaluate_b01
    svc.FAMILY_RULES["B01"] = ["PAYMENT_UNAUTHORIZED_REFUND_CURRENT"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
