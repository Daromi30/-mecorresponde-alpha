from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import Case


_INSTALLED = False


def install_case_state_policy() -> None:
    """Keep terminal case state and lifecycle timestamps consistent.

    `closed_at` is the technical time MECORRESPONDE persisted the terminal state. It is
    deliberately separate from user-supplied real-world dates such as Outcome.resolved_on.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def close_resolved_cases(session: Session, flush_context, instances) -> None:  # noqa: ANN001
        for obj in set(session.new).union(session.dirty):
            if isinstance(obj, Case) and obj.status == "RESOLVED" and obj.closed_at is None:
                obj.closed_at = datetime.now(timezone.utc)

    _INSTALLED = True
