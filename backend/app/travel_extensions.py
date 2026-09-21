from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.v01 import evaluate_v01

_INSTALLED = False
_PREVIOUS_SEED = svc.seed_legal


def _seed_legal(db: Session):
    rules = _PREVIOUS_SEED(db)
    svc._ensure_source(
        db,
        "EU261_2004",
        "EUR-Lex / Parlamento Europeo y Consejo de la Unión Europea",
        "Reglamento (CE) n.º 261/2004 sobre compensación y asistencia a los pasajeros aéreos",
        "https://eur-lex.europa.eu/eli/reg/2004/261/oj",
        date(2004, 2, 17),
    )
    rules["AIR_CANCELLATION_REFUND_CURRENT"] = svc._ensure_rule(
        db,
        "AIR_CANCELLATION_REFUND_CURRENT",
        1,
        date(2005, 2, 17),
        "EU261_2004",
        "3, 5.1(a), 8.1(a)",
        {
            "carrier_cancelled_flight": True,
            "confirmed_reservation": True,
            "departure_airport_in_eu": True,
            "passenger_choice": "refund",
            "single_flight_booking": True,
        },
        {
            "refund_ticket_cost": True,
            "refund_period_days": 7,
            "article_7_compensation_separate": True,
        },
        (
            "En una cancelación cubierta, el artículo 5.1(a) remite al artículo 8. Para la ruta automatizada V01, "
            "el pasajero elige reembolso de un único vuelo con precio documentado y salida desde la UE. El artículo "
            "8.1(a) prevé el reembolso en siete días. La compensación del artículo 7 se analiza por separado."
        ),
    )
    return rules


def install_travel_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["V01"] = evaluate_v01
    svc.FAMILY_RULES["V01"] = ["AIR_CANCELLATION_REFUND_CURRENT"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
