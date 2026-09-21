from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .calendar_clock import spain_today
from .models import Action, Case


_REGISTERED_WAIT_ACTIONS = frozenset({
    "WAIT_UNTIL_DELIVERY_DUE",
    "WAIT_ADDITIONAL_DELIVERY_PERIOD",
    "WAIT_WITHDRAWAL_REFUND_PERIOD",
    "WAIT_S01_ARTICLE_18_FORTY_DAYS",
})


def known_resumable_wait_actions() -> tuple[str, ...]:
    return tuple(sorted(_REGISTERED_WAIT_ACTIONS))


def _raw(facts, key: str, default=None):
    fact = facts.get(key)
    return fact.value if fact is not None else default


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _wait_milestone_elapsed(action_type: str, facts) -> bool:
    analysis_date = _as_date(_raw(facts, "system.analysis_date")) or spain_today()

    if action_type == "WAIT_UNTIL_DELIVERY_DUE":
        order_date = _as_date(_raw(facts, "purchase.order_date"))
        agreed = _raw(facts, "purchase.delivery_date_was_agreed")
        agreed_date = _as_date(_raw(facts, "purchase.agreed_delivery_date"))
        due_date = agreed_date if agreed is True else (order_date + timedelta(days=30) if order_date else None)
        return due_date is not None and analysis_date > due_date

    if action_type == "WAIT_ADDITIONAL_DELIVERY_PERIOD":
        deadline = _as_date(_raw(facts, "purchase.additional_delivery_period_deadline"))
        return deadline is not None and analysis_date > deadline

    if action_type == "WAIT_WITHDRAWAL_REFUND_PERIOD":
        sent_date = _as_date(_raw(facts, "purchase.withdrawal_sent_date"))
        refund_due_date = sent_date + timedelta(days=14) if sent_date else None
        return refund_due_date is not None and analysis_date > refund_due_date

    if action_type == "WAIT_S01_ARTICLE_18_FORTY_DAYS":
        received_date = _as_date(_raw(facts, "insurance.claim_declaration_received_date"))
        due_date = received_date + timedelta(days=40) if received_date else None
        return due_date is not None and analysis_date > due_date

    return False


def resume_wait_action(db: Session, case: Case):
    """Re-evaluate a diagnosed temporal wait only after its registered milestone elapsed.

    Ordinary `/diagnose` replay remains blocked. This transition is deliberately narrower:
    the current action must be a registered WAIT action, must still be OPEN, and its factual
    calendar milestone must have elapsed according to the Spain civil-date analysis clock.
    Before the milestone there is zero mutation. Once elapsed, the old wait becomes historical
    only in the same transaction that successfully persists the replacement diagnosis.
    """
    if case.status != "DIAGNOSED" or not case.current_action_id:
        raise ValueError("This case is not waiting on a resumable temporal milestone")

    current = db.get(Action, case.current_action_id)
    if (
        current is None
        or current.case_id != case.id
        or current.status != "OPEN"
        or current.type not in _REGISTERED_WAIT_ACTIONS
    ):
        raise ValueError("The current action is not a resumable wait")

    facts = svc.latest_facts(db, case.id)
    if not _wait_milestone_elapsed(current.type, facts):
        raise ValueError("The waiting milestone has not elapsed yet")

    previous_action_id = current.id
    previous_decision_id = case.current_decision_id
    current.status = "COMPLETED"
    current.completed_at = datetime.now(timezone.utc)
    case.current_action_id = None
    case.current_decision_id = None
    case.status = "INTAKE"
    svc.audit(
        db,
        case.id,
        "WAIT_MILESTONE_RECHECK_STARTED",
        {
            "previous_action_id": previous_action_id,
            "previous_decision_id": previous_decision_id,
            "wait_action": current.type,
            "analysis_date": str(_as_date(_raw(facts, "system.analysis_date")) or spain_today()),
        },
    )

    try:
        # diagnose() owns the successful transaction commit. Keeping the old wait
        # transition pending until then prevents a failed reanalysis from leaving
        # the case stranded in INTAKE with no current decision/action.
        result, decision, action = svc.diagnose(db, case)
    except Exception:
        db.rollback()
        raise

    svc.audit(
        db,
        case.id,
        "WAIT_MILESTONE_RECHECK_COMPLETED",
        {
            "previous_action_id": previous_action_id,
            "new_decision_id": decision.id,
            "new_action_id": action.id,
            "new_action": action.type,
        },
    )
    db.commit()
    return result, decision, action
