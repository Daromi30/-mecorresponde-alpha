from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.s01 import evaluate_s01


def register_insurance_family() -> None:
    svc.EVALUATORS["S01"] = evaluate_s01
    svc.FAMILY_RULES["S01"] = ["INSURANCE_MINIMUM_PAYMENT_CURRENT"]


def seed_insurance_legal(db: Session) -> dict[str, object]:
    svc._ensure_source(
        db,
        "LCS_1980",
        "BOE / Jefatura del Estado",
        "Ley 50/1980, de 8 de octubre, de Contrato de Seguro",
        "https://www.boe.es/eli/es/l/1980/10/08/50/con",
        date(1980, 10, 17),
    )
    rule = svc._ensure_rule(
        db,
        "INSURANCE_MINIMUM_PAYMENT_CURRENT",
        1,
        date(1981, 4, 17),
        "LCS_1980",
        "18",
        {
            "claim_declaration_received": True,
            "receipt_date_evidenced": True,
            "minimum_amount_acknowledged": True,
        },
        {
            "minimum_payment_within_days": 40,
            "coverage_and_loss_valuation_not_decided": True,
            "article_20_default_interest_separate": True,
        },
        (
            "S01 automatiza únicamente un importe mínimo que el propio asegurador ha reconocido o cuantificado "
            "de forma verificable. El artículo 18 exige el pago del importe mínimo que pueda deber dentro de cuarenta "
            "días desde la recepción de la declaración del siniestro. Cobertura, causalidad, valoración total y mora "
            "del artículo 20 quedan fuera de esta ruta automática."
        ),
    )
    return {"INSURANCE_MINIMUM_PAYMENT_CURRENT": rule}
