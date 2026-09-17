from datetime import date

import pytest
from sqlalchemy import func, select

from app import services_v2 as svc
from app.models import Action, AuditEvent, Case, Decision
from app.wait_resume import resume_wait_action


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _count(db, model, case_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id)) or 0)


def test_failed_wait_resume_rolls_back_original_wait_snapshot(client, db, monkeypatch):
    monkeypatch.setattr("app.analysis_clock_policy.spain_today", lambda: date(2026, 9, 17))
    monkeypatch.setattr("app.wait_resume.spain_today", lambda: date(2026, 9, 17))

    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C04"

    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": "2026-08-18",
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
    }.items():
        _fact(client, case_id, key, value)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "WAIT_UNTIL_DELIVERY_DUE"
    old_action_id = diagnosis.json()["action_id"]
    old_decision_id = diagnosis.json()["decision_id"]

    monkeypatch.setattr("app.analysis_clock_policy.spain_today", lambda: date(2026, 9, 18))
    monkeypatch.setattr("app.wait_resume.spain_today", lambda: date(2026, 9, 18))

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    before = {
        "decisions": _count(db, Decision, case_id),
        "actions": _count(db, Action, case_id),
        "events": _count(db, AuditEvent, case_id),
    }

    def fail_diagnosis(_db, _case):
        raise RuntimeError("synthetic diagnosis failure")

    monkeypatch.setattr(svc, "diagnose", fail_diagnosis)

    with pytest.raises(RuntimeError, match="synthetic diagnosis failure"):
        resume_wait_action(db, case)

    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "DIAGNOSED"
    assert restored.current_action_id == old_action_id
    assert restored.current_decision_id == old_decision_id

    old_action = db.get(Action, old_action_id)
    assert old_action is not None
    assert old_action.status == "OPEN"
    assert old_action.completed_at is None

    assert _count(db, Decision, case_id) == before["decisions"]
    assert _count(db, Action, case_id) == before["actions"]
    assert _count(db, AuditEvent, case_id) == before["events"]
