from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.r01 import evaluate_r01


def register_rental_family() -> None:
    svc.EVALUATORS["R01"] = evaluate_r01
    svc.FAMILY_RULES["R01"] = ["RENTAL_DEPOSIT_RETURN_CURRENT"]


def seed_rental_legal(db: Session) -> dict[str, object]:
    svc._ensure_source(
        db,
        "LAU_1994",
        "BOE / Jefatura del Estado",
        "Ley 29/1994, de 24 de noviembre, de Arrendamientos Urbanos",
        "https://www.boe.es/eli/es/l/1994/11/24/29/con",
        date(1994, 11, 25),
    )
    rule = svc._ensure_rule(
        db,
        "RENTAL_DEPOSIT_RETURN_CURRENT",
        1,
        date(1995, 1, 1),
        "LAU_1994",
        "36.4",
        {
            "urban_lease": True,
            "lease_ended": True,
            "statutory_cash_deposit": True,
            "refundable_balance_confirmed": True,
        },
        {
            "return_confirmed_balance": True,
            "legal_interest_after_one_month_from_keys": True,
            "interest_amount_requires_separate_rate_source": True,
        },
        (
            "R01 automatiza únicamente un saldo de fianza en metálico ya determinado o reconocido. "
            "El artículo 36.4 establece que ese saldo devenga el interés legal una vez transcurrido un mes "
            "desde la entrega de llaves sin restitución. R01 no decide deducciones discutidas ni calcula "
            "el importe de intereses sin una fuente oficial separada para el tipo aplicable."
        ),
    )
    return {"RENTAL_DEPOSIT_RETURN_CURRENT": rule}
