from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import (
    Action,
    AuditEvent,
    Calculation,
    Case,
    Counterargument,
    Decision,
    RuleEvaluation,
)
from app.routers import cases_v2 as case_routes


def _count(db, model, case_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(model).where(model.case_id == case_id)
        )
        or 0
    )


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": key,
            "value": value,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


def test_failure_after_real_diagnosis_rolls_back_entire_motor_snapshot(client, db, monkeypatch):
    created = client.post(
        "/api/cases",
        json={"message": "La factura eléctrica me ha cobrado de más"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    _fact(client, case_id, "electricity.billing.invoice_date", "2026-07-01")
    _fact(client, case_id, "electricity.billing.billed_amount", 150.0)
    _fact(client, case_id, "electricity.billing.correct_amount", 100.0)

    db.expire_all()
    before_case = db.get(Case, case_id)
    assert before_case is not None
    assert before_case.status == "INTAKE"
    assert before_case.current_decision_id is None
    assert before_case.current_action_id is None

    models = (Decision, Action, RuleEvaluation, Calculation, Counterargument, AuditEvent)
    before = {model: _count(db, model, case_id) for model in models}

    real_diagnose = case_routes.diagnose

    def fail_after_real_diagnosis(db_session, case):
        real_diagnose(db_session, case)
        raise RuntimeError("synthetic post-diagnosis failure")

    monkeypatch.setattr(case_routes, "diagnose", fail_after_real_diagnosis)

    with pytest.raises(RuntimeError, match="synthetic post-diagnosis failure"):
        client.post(f"/api/cases/{case_id}/diagnose")

    db.rollback()
    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "INTAKE"
    assert restored.current_decision_id is None
    assert restored.current_action_id is None
    for model in models:
        assert _count(db, model, case_id) == before[model], model.__name__
