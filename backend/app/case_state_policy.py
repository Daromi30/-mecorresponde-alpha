from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from .action_contract import action_kind
from .models import Action, AuditEvent, Case


_INSTALLED = False
_TERMINAL_CASE_STATUSES = frozenset({"RESOLVED", "CLOSED_UNSUPPORTED"})


def install_case_state_policy() -> None:
    """Keep case state, action state and technical closure mutually consistent.

    `closed_at` is the technical time MECORRESPONDE persisted the current terminal state. It
    is deliberately separate from user-supplied real-world dates such as Outcome.resolved_on.
    If a terminal case is legitimately reopened into an active workflow, its current
    `closed_at` must be cleared; the audit trail preserves the historical transition.

    Informational Motor actions are conclusions, not work still waiting to happen. Once a
    diagnosis ends in an informational action, keep the Decision current for explanation and
    traceability, but complete that Action and clear `current_action_id`. A later user fact or
    confirmed document fact can still invalidate the diagnosis through the normal fact-write
    policy and return the case to INTAKE.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def synchronize_case_closure(session: Session, flush_context, instances) -> None:  # noqa: ANN001
        now = datetime.now(timezone.utc)
        for obj in set(session.new).union(session.dirty):
            if not isinstance(obj, Case):
                continue

            if obj.status == "DIAGNOSED" and obj.current_action_id:
                action = session.get(Action, obj.current_action_id)
                if (
                    action is not None
                    and action.case_id == obj.id
                    and action.status not in {"COMPLETED", "SUPERSEDED"}
                    and action_kind(action.type) == "informational"
                ):
                    action.status = "COMPLETED"
                    action.completed_at = now
                    obj.current_action_id = None
                    session.add(
                        AuditEvent(
                            case_id=obj.id,
                            event_type="INFORMATIONAL_ACTION_COMPLETED",
                            payload_json={
                                "action_id": action.id,
                                "action_type": action.type,
                                "decision_id": obj.current_decision_id,
                                "family": obj.family,
                            },
                        )
                    )

            if obj.status in _TERMINAL_CASE_STATUSES:
                if obj.closed_at is None:
                    obj.closed_at = now
            elif obj.closed_at is not None:
                obj.closed_at = None

    _INSTALLED = True
