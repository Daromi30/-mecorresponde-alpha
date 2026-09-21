from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.a01 import evaluate_a01


def register_automotive_family() -> None:
    svc.EVALUATORS["A01"] = evaluate_a01
    svc.FAMILY_RULES["A01"] = ["AUTOMOTIVE_REPAIR_GUARANTEE_CURRENT"]


def seed_automotive_legal(db: Session) -> dict[str, object]:
    svc._ensure_source(
        db,
        "RD1457_1986",
        "BOE / Presidencia del Gobierno",
        "Real Decreto 1457/1986, de 10 de enero, sobre talleres de reparación de vehículos automóviles",
        "https://www.boe.es/eli/es/rd/1986/01/10/1457/con",
        date(1986, 7, 16),
    )
    rule = svc._ensure_rule(
        db,
        "AUTOMOTIVE_REPAIR_GUARANTEE_CURRENT",
        1,
        date(1986, 8, 5),
        "RD1457_1986",
        "16.1-16.6",
        {
            "spanish_workshop": True,
            "non_industrial_vehicle": True,
            "same_repaired_part_failure": True,
            "within_three_months": True,
            "within_2000_km": True,
        },
        {
            "free_repair": True,
            "guarantee_months": 3,
            "guarantee_km": 2000,
            "third_party_manipulation_requires_review": True,
            "refused_hidden_anomaly_exception_requires_review": True,
        },
        (
            "A01 automatiza únicamente una nueva avería acreditada en la parte reparada de un vehículo no industrial, "
            "dentro de tres meses y 2.000 km desde la entrega. El artículo 16.4 exige reparación gratuita previa comunicación "
            "del usuario. Intervención posterior de terceros, relación dudosa con la parte reparada o la excepción del "
            "artículo 16.6 se remiten a revisión humana."
        ),
    )
    return {"AUTOMOTIVE_REPAIR_GUARANTEE_CURRENT": rule}
