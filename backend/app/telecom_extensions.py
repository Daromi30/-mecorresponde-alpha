from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.t01 import evaluate_t01

_INSTALLED = False
_PREVIOUS_SEED = svc.seed_legal


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    svc._ensure_source(
        db,
        "RD899_2009",
        "BOE / Ministerio de la Presidencia",
        "Real Decreto 899/2009, de 22 de mayo, por el que se aprueba la carta de derechos del usuario de los servicios de comunicaciones electrónicas",
        "https://www.boe.es/eli/es/rd/2009/05/22/899",
        date(2009, 5, 30),
    )
    rules["TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION"] = svc._ensure_rule(
        db,
        "TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION",
        1,
        date(2009, 8, 30),
        "RD899_2009",
        "16",
        {"temporary_fixed_internet_interruption": True},
        {
            "refund_fixed_fees_prorated_by_interruption_time": True,
            "automatic_credit_if_more_than_6_hours_between_8_and_22": True,
            "bundle_without_separate_commercialization_internet_share_percent": 50,
            "article_16_2_exclusions_apply": True,
        },
        (
            "La interrupción temporal del acceso a internet da lugar al prorrateo de la cuota de abono y otras cuotas fijas. "
            "Si supera seis horas, continuas o discontinuas, entre las 8 y las 22, el abono debe realizarse automáticamente "
            "en la factura inmediata. En paquetes sin precio separado y cuyos servicios no se comercializan por separado, "
            "el precio de internet se considera el 50 % del total. Se respetan las exclusiones del artículo 16.2."
        ),
    )
    return rules


def install_telecom_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["T01"] = evaluate_t01
    svc.FAMILY_RULES["T01"] = ["TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
