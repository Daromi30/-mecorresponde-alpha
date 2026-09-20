from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case
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


def test_failure_after_real_claim_package_rolls_back_ready_state_and_new_action(client, db, monkeypatch):
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
    original_action_id = diagnosis.json()["action_id"]
    original_decision_id = diagnosis.json()["decision_id"]

    db.expire_all()
    before_case = db.get(Case, case_id)
    assert before_case is not None
    assert before_case.status == "DIAGNOSED"
    original_action = db.get(Action, original_action_id)
    assert original_action is not None
    assert original_action.status == "OPEN"

    before_actions = _count(db, Action, case_id)
    before_audits = _count(db, AuditEvent, case_id)

    real_prepare = case_routes.prepare_claim_package

    def fail_after_real_prepare(db_session, case):
        real_prepare(db_session, case)
        raise RuntimeError("synthetic post-package failure")

    monkeypatch.setattr(case_routes, "prepare_claim_package", fail_after_real_prepare)

    with pytest.raises(RuntimeError, match="synthetic post-package failure"):
        client.post(f"/api/cases/{case_id}/prepare-claim")

    db.rollback()
    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "DIAGNOSED"
    assert restored.current_decision_id == original_decision_id
    assert restored.current_action_id == original_action_id
    restored_action = db.get(Action, original_action_id)
    assert restored_action is not None
    assert restored_action.status == "OPEN"
    assert restored_action.completed_at is None
    assert _count(db, Action, case_id) == before_actions
    assert _count(db, AuditEvent, case_id) == before_audits
