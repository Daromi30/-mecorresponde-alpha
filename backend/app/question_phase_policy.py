from __future__ import annotations

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Case


_INSTALLED = False
_LOCKED_QUESTION_STATUSES = frozenset({
    "HUMAN_REVIEW",
    "REANALYZING",
    "WAITING_RESPONSE",
    "RESPONSE_RECEIVED",
    "RESOLVED_PENDING_EXECUTION",
    "RESOLVED",
    "CLOSED_UNSUPPORTED",
})
_NO_QUESTION = {"done": True, "question": None, "field": None}


def install_question_phase_policy() -> None:
    """Keep claimant question API aligned with the case lifecycle.

    Guided questions are an intake/re-entry mechanism, not a way to mutate a case while a
    protected review, submitted claim, response analysis or terminal outcome owns the next
    transition. DIAGNOSED deliberately remains unlocked because registered MONITOR/CHECK
    follow-ups use the same question engine to resume the Motor safely.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_get_next_question = svc.get_next_question

    def get_next_question_for_active_phase(db: Session, case: Case):
        if case.status in _LOCKED_QUESTION_STATUSES:
            return dict(_NO_QUESTION)
        return previous_get_next_question(db, case)

    svc.get_next_question = get_next_question_for_active_phase
    _INSTALLED = True
