from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import Case


_INSTALLED = False
_TERMINAL_CASE_STATUSES = frozenset({"RESOLVED", "CLOSED_UNSUPPORTED"})


def install_case_state_policy() -> None:
    """Keep case state and the technical closure timestamp mutually consistent.

    `closed_at` is the technical time MECORRESPONDE persisted the current terminal state. It
    is deliberately separate from user-supplied real-world dates such as Outcome.resolved_on.
    If a terminal case is legitimately reopened into an active workflow, its current
    `closed_at` must be cleared; the audit trail preserves the historical transition.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def synchronize_case_closure(session: Session, flush_context, instances) -> None:  # noqa: ANN001
        for obj in set(session.new).union(session.dirty):
            if not isinstance(obj, Case):
                continue
            if obj.status in _TERMINAL_CASE_STATUSES:
                if obj.closed_at is None:
                    obj.closed_at = datetime.now(timezone.utc)
            elif obj.closed_at is not None:
                obj.closed_at = None

    _INSTALLED = True
