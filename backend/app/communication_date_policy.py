from __future__ import annotations

from datetime import date

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import AuditEvent, Communication


_INSTALLED = False


def _calendar_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def install_communication_date_policy() -> None:
    """Persist user-supplied calendar dates without inventing communication times.

    Evidenced routes emit allowlisted audit events containing the real submitted/received
    calendar date. Those events may backfill a normalized Communication when its calendar
    date is still missing, but they must never overwrite an already structured date. This
    keeps Communication as the canonical record while preserving migration compatibility.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def sync_communication_calendar_dates(session: Session, _flush_context, _instances) -> None:
        pending_audits = [row for row in session.new if isinstance(row, AuditEvent)]
        if not pending_audits:
            return

        for audit in pending_audits:
            payload = audit.payload_json or {}
            if audit.event_type == "CLAIM_SUBMITTED":
                occurred_on = _calendar_date(payload.get("submitted_on"))
                if occurred_on is None:
                    continue
                candidates = [
                    row
                    for row in session.new
                    if isinstance(row, Communication)
                    and row.case_id == audit.case_id
                    and row.direction == "OUTBOUND"
                    and row.occurred_on is None
                ]
                if len(candidates) == 1:
                    candidates[0].occurred_on = occurred_on
                continue

            if audit.event_type != "COMPANY_RESPONSE_RECORDED":
                continue
            occurred_on = _calendar_date(payload.get("received_on"))
            communication_id = payload.get("communication_id")
            if occurred_on is None or not communication_id:
                continue
            communication = session.get(Communication, str(communication_id))
            if (
                communication is not None
                and communication.case_id == audit.case_id
                and communication.direction == "INBOUND"
                and communication.occurred_on is None
            ):
                communication.occurred_on = occurred_on

    _INSTALLED = True
