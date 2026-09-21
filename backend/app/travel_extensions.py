from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .engine.v01 import evaluate_v01
from .engine.v02 import evaluate_v02
from .engine.v03 import evaluate_v03

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
    rules["AIR_FIVE_HOUR_DELAY_REFUND_CURRENT"] = svc._ensure_rule(
        db,
        "AIR_FIVE_HOUR_DELAY_REFUND_CURRENT",
        1,
        date(2005, 2, 17),
        "EU261_2004",
        "3, 6.1(iii), 8.1(a)",
        {
            "departure_delay_hours_at_least": 5,
            "confirmed_reservation": True,
            "departure_airport_in_eu": True,
            "passenger_requests_refund": True,
            "passenger_did_not_take_delayed_flight": True,
            "single_flight_booking": True,
        },
        {
            "refund_ticket_cost": True,
            "refund_period_days": 7,
            "delay_compensation_separate": True,
        },
        (
            "Cuando el retraso alcanza al menos cinco horas, el artículo 6.1(iii) remite al reembolso "
            "del artículo 8.1(a). V02 automatiza únicamente un vuelo único no utilizado, con precio "
            "documentado y salida desde la UE; cualquier compensación adicional se analiza por separado."
        ),
    )
    rules["AIR_INVOLUNTARY_DENIED_BOARDING_COMPENSATION_CURRENT"] = svc._ensure_rule(
        db,
        "AIR_INVOLUNTARY_DENIED_BOARDING_COMPENSATION_CURRENT",
        1,
        date(2005, 2, 17),
        "EU261_2004",
        "2(j), 3.2, 4.3, 7",
        {
            "involuntary_denied_boarding": True,
            "presentation_requirements_met": True,
            "reasonable_ground_exclusion": False,
        },
        {
            "article_7_compensation": True,
            "distance_bands_eur": {"le_1500": 250, "middle": 400, "other_gt_3500": 600},
            "rerouting_reduction_percent": 50,
        },
        (
            "La denegación involuntaria de embarque comprendida en el artículo 2(j), con las condiciones del artículo 3.2, "
            "da derecho a compensación inmediata conforme a los artículos 4.3 y 7. La posible reducción del 50 % depende "
            "del tiempo de llegada del transporte alternativo y de la banda de distancia."
        ),
    )
    return rules


def install_travel_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    svc.EVALUATORS["V01"] = evaluate_v01
    svc.FAMILY_RULES["V01"] = ["AIR_CANCELLATION_REFUND_CURRENT"]
    svc.EVALUATORS["V02"] = evaluate_v02
    svc.FAMILY_RULES["V02"] = ["AIR_FIVE_HOUR_DELAY_REFUND_CURRENT"]
    svc.EVALUATORS["V03"] = evaluate_v03
    svc.FAMILY_RULES["V03"] = ["AIR_INVOLUNTARY_DENIED_BOARDING_COMPENSATION_CURRENT"]
    svc.seed_legal = _seed_legal
    _INSTALLED = True
