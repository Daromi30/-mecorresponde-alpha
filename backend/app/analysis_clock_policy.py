from __future__ import annotations

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .calendar_clock import spain_today
from .engine.common import FactValue


_INSTALLED = False


def install_analysis_clock_policy() -> None:
    """Supply a jurisdiction-correct, non-persisted analysis date to every evaluator.

    Base diagnosis historically fell back to ``date.today()`` on the application server.
    Render runs in UTC, so around midnight that can differ from Spain's civil date. Injecting
    the date through the shared fact snapshot makes every family use Europe/Madrid without
    creating claimant evidence or a fake real-world event.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_latest_facts = svc.latest_facts

    def latest_facts_with_spain_clock(db: Session, case_id: str):
        facts = previous_latest_facts(db, case_id)
        facts["system.analysis_date"] = FactValue(
            value=spain_today().isoformat(),
            state="confirmed",
            user_confirmed=False,
        )
        return facts

    svc.latest_facts = latest_facts_with_spain_clock
    _INSTALLED = True
