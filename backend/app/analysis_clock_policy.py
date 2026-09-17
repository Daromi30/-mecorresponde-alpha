from __future__ import annotations

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .calendar_clock import spain_today
from .engine.common import FactValue


_INSTALLED = False


def install_analysis_clock_policy() -> None:
    """Supply a jurisdiction-correct, non-persisted analysis date to the Motor.

    Evaluators consume ``system.analysis_date`` so legal/temporal analysis never falls back
    to the application server's UTC civil date. Guided questions that need the current date
    use the same Europe/Madrid clock directly in their question module; keeping that logic
    there avoids a second C04 question implementation in this policy layer.
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
