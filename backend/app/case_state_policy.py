from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import Case


_INSTALLED = False
_TERMINAL_CASE_STATUSES = frozenset({"RESOLVED", "CLOSED_UNSUPPORTED"})


def install_case_state_policy() -> None:
    """Keep terminal case state and lifecycle timestamps consistent.

    `closed_at` is the technical time MECORRESPONDE persisted the terminal state. It is
    deliberately separate from user-supplied real-world dates such as Outcome.resolved_on.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def close_terminal_cases(session: Session, flush_context, instances) -> None:  # noqa: ANN001
        for obj in set(session.new).union(session.dirty):
            if (
                isinstance(obj, Case)
                and obj.status in _TERMINAL_CASE_STATUSES
                and obj.closed_at is None
            ):
                obj.closed_at = datetime.now(timezone.utc)

    _INSTALLED = True
