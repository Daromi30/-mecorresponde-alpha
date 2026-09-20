from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.calendar_clock import spain_today
from app.models import Action, AuditEvent, Case, Communication, Deadline
from app.routers import cases_v2 as case_routes


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _count(db, model, case_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id))
        or 0
    )


def test_submission_response_failure_rolls_back_wait_communication_audit_and_deadline(
    client, db, monkeypatch
):
    created = client.post(
        "/api/cases",
        json={"message": "La factura eléctrica me ha cobrado de más"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    _fact(client, case_id, "electricity.billing.invoice_date", "2026-07-01")
    _fact(client, case_id, "electricity.billing.billed_amount", 150.0)
    _fact(client, case_id, "electricity.billing.correct_amount", 100.0)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, prepared.text

    before = client.get(f"/api/cases/{case_id}").json()
    assert before["status"] == "READY_TO_SUBMIT"
    action_id = before["current_action_id"]
    action = db.get(Action, action_id)
    assert action is not None and action.type == "SUBMIT_INITIAL_CLAIM" and action.status == "READY"

    counts = {
        "actions": _count(db, Action, case_id),
        "communications": _count(db, Communication, case_id),
        "audits": _count(db, AuditEvent, case_id),
        "deadlines": _count(db, Deadline, case_id),
    }

    def fail_response(_case):
        raise RuntimeError("synthetic submission response failure")

    monkeypatch.setattr(case_routes, "_build_submission_response", fail_response)

    with pytest.raises(RuntimeError, match="synthetic submission response failure"):
        client.post(
            f"/api/cases/{case_id}/submission",
            json={
                "submitted_on": spain_today().isoformat(),
                "channel": "email",
                "reference_number": "SYNTHETIC-ROLLBACK",
            },
        )

    db.rollback()
    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "READY_TO_SUBMIT"
    assert restored.current_action_id == action_id

    action = db.get(Action, action_id)
    assert action is not None and action.status == "READY"
    assert _count(db, Action, case_id) == counts["actions"]
    assert _count(db, Communication, case_id) == counts["communications"]
    assert _count(db, AuditEvent, case_id) == counts["audits"]
    assert _count(db, Deadline, case_id) == counts["deadlines"]
