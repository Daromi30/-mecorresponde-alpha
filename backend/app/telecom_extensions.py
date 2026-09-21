from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.t01 import evaluate_t01
from .engine.t02 import evaluate_t02

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
    svc._ensure_source(
        db,
        "LGT_2022",
        "BOE / Jefatura del Estado",
        "Ley 11/2022, de 28 de junio, General de Telecomunicaciones",
        "https://www.boe.es/eli/es/l/2022/06/28/11",
        date(2022, 6, 29),
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
    rules["TELECOM_CONTRACT_CHANGE_FREE_TERMINATION"] = svc._ensure_rule(
        db,
        "TELECOM_CONTRACT_CHANGE_FREE_TERMINATION",
        1,
        date(2022, 6, 30),
        "LGT_2022",
        "67.8 y 67.10",
        {"announced_contract_change": True, "article_67_8_exception": False},
        {
            "free_termination_right": True,
            "notice_at_least_one_month": True,
            "exercise_within_one_month_from_notice": True,
            "clear_durable_notice": True,
            "valid_contractual_reason_required_for_unilateral_change": True,
            "retained_subsidized_terminal_may_require_compensation": True,
        },
        (
            "Ante cambios contractuales no incluidos en las excepciones del artículo 67.8, el usuario final tiene derecho "
            "a resolver sin coste adicional, con comunicación previa de al menos un mes e información simultánea del derecho. "
            "El derecho puede ejercerse durante un mes desde la comunicación. El artículo 67.10 mantiene la posible compensación "
            "por un terminal subvencionado que el usuario conserve."
        ),
    )
    return rules


def install_telecom_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["T01"] = evaluate_t01
    svc.FAMILY_RULES["T01"] = ["TELECOM_FIXED_INTERNET_INTERRUPTION_COMPENSATION"]
    svc.EVALUATORS["T02"] = evaluate_t02
    svc.FAMILY_RULES["T02"] = ["TELECOM_CONTRACT_CHANGE_FREE_TERMINATION"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
