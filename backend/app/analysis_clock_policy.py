from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .calendar_clock import spain_today
from .engine.common import FactValue


_INSTALLED = False


def _raw(facts: dict[str, FactValue], key: str):
    fact = facts.get(key)
    return fact.value if fact is not None else None


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def install_analysis_clock_policy() -> None:
    """Supply a jurisdiction-correct, non-persisted analysis date across Motor entry points.

    Base diagnosis historically fell back to ``date.today()`` on the application server.
    Render runs in UTC, so around midnight that can differ from Spain's civil date. Injecting
    the date through the shared fact snapshot makes every evaluator use Europe/Madrid without
    creating claimant evidence or a fake real-world event. C04's guided-question helper also
    had one direct server-date comparison; the wrapper below corrects only that overdue edge
    while leaving all ordinary question ordering to the existing family question engine.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_latest_facts = svc.latest_facts
    previous_get_next_question = svc.get_next_question

    def latest_facts_with_spain_clock(db: Session, case_id: str):
        facts = previous_latest_facts(db, case_id)
        facts["system.analysis_date"] = FactValue(
            value=spain_today().isoformat(),
            state="confirmed",
            user_confirmed=False,
        )
        return facts

    def get_next_question_with_spain_clock(db: Session, case):
        result = previous_get_next_question(db, case)
        if case.family != "C04":
            return result

        facts = svc.latest_facts(db, case.id)
        required = (
            "purchase.order_date",
            "purchase.delivered",
            "purchase.delivery_date_was_agreed",
            "purchase.seller_refused_delivery",
            "purchase.delivery_date_essential",
        )
        if any(key not in facts for key in required):
            return result
        if _raw(facts, "purchase.delivered") is True:
            return result

        order_date = _as_date(_raw(facts, "purchase.order_date"))
        agreed = _raw(facts, "purchase.delivery_date_was_agreed")
        agreed_date = _as_date(_raw(facts, "purchase.agreed_delivery_date"))
        if agreed is True and agreed_date is None:
            return result
        due_date = agreed_date if agreed is True else (order_date + timedelta(days=30) if order_date else None)
        analysis_date = _as_date(_raw(facts, "system.analysis_date")) or spain_today()
        immediate = _raw(facts, "purchase.seller_refused_delivery") is True or bool(
            _raw(facts, "purchase.delivery_date_essential") is True
            and due_date
            and analysis_date > due_date
        )
        if not due_date or analysis_date <= due_date or immediate:
            return result

        if "purchase.additional_delivery_period_requested" not in facts:
            return {
                "done": False,
                "question": "Después de vencer la entrega, ¿diste al vendedor un plazo adicional para que cumpliera?",
                "field": "purchase.additional_delivery_period_requested",
                "input_type": "boolean",
            }
        if (
            _raw(facts, "purchase.additional_delivery_period_requested") is True
            and "purchase.additional_delivery_period_deadline" not in facts
        ):
            return {
                "done": False,
                "question": "¿Hasta qué fecha le diste ese plazo adicional?",
                "field": "purchase.additional_delivery_period_deadline",
                "input_type": "date",
            }
        return result

    svc.latest_facts = latest_facts_with_spain_clock
    svc.get_next_question = get_next_question_with_spain_clock
    _INSTALLED = True
