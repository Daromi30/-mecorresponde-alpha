from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Fact
from app.routers import cases_v2 as case_routes


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _fact_count(db, case_id: str, key: str | None = None) -> int:
    stmt = select(func.count()).select_from(Fact).where(Fact.case_id == case_id)
    if key is not None:
        stmt = stmt.where(Fact.key == key)
    return int(db.scalar(stmt) or 0)


def test_fact_response_failure_rolls_back_new_fact_and_analysis_invalidation(client, db, monkeypatch):
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
    decision_id = diagnosis.json()["decision_id"]
    action_id = diagnosis.json()["action_id"]

    db.expire_all()
    before_case = db.get(Case, case_id)
    assert before_case is not None and before_case.status == "DIAGNOSED"
    before_fact_count = _fact_count(db, case_id, "electricity.billing.correct_amount")
    before_audits = int(
        db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id))
        or 0
    )

    def fail_next_question(*_args, **_kwargs):
        raise RuntimeError("synthetic fact next-question failure")

    monkeypatch.setattr(case_routes, "get_next_question", fail_next_question)

    with pytest.raises(RuntimeError, match="synthetic fact next-question failure"):
        client.post(
            f"/api/cases/{case_id}/facts",
            json={
                "key": "electricity.billing.correct_amount",
                "value": 90.0,
                "state": "confirmed",
                "user_confirmed": True,
            },
        )

    db.rollback()
    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "DIAGNOSED"
    assert restored.current_decision_id == decision_id
    assert restored.current_action_id == action_id
    action = db.get(Action, action_id)
    assert action is not None and action.status == "OPEN"
    assert _fact_count(db, case_id, "electricity.billing.correct_amount") == before_fact_count
    assert int(
        db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id))
        or 0
    ) == before_audits


def test_charge_response_failure_rolls_back_charge_fact(client, db, monkeypatch):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    _fact(client, case_id, "electricity.billing.same_debt", True)

    key = "electricity.billing.duplicate_charges"
    before = _fact_count(db, case_id, key)

    def fail_next_question(*_args, **_kwargs):
        raise RuntimeError("synthetic charges next-question failure")

    monkeypatch.setattr(case_routes, "get_next_question", fail_next_question)

    with pytest.raises(RuntimeError, match="synthetic charges next-question failure"):
        client.post(
            f"/api/cases/{case_id}/charges",
            json={
                "charges": [
                    {"amount": 74.30, "evidence_verified": True},
                    {"amount": 74.30, "evidence_verified": True},
                ]
            },
        )

    db.rollback()
    assert _fact_count(db, case_id, key) == before
