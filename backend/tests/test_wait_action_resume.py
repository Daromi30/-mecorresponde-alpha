from __future__ import annotations

import inspect
import re
from datetime import date

from sqlalchemy import func, select

from app import services_v2 as svc
from app.action_contract import action_kind
from app.models import Action, AuditEvent, Case, Decision
from app.wait_resume import known_resumable_wait_actions


_ACTION_LITERAL = re.compile(r"next_action\s*=\s*[\"']([A-Z0-9_]+)[\"']")


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _c04_case(client, *, order_date: str, additional_deadline: str | None = None) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C04"
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": order_date,
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
    }
    if additional_deadline is not None:
        facts["purchase.additional_delivery_period_requested"] = True
        facts["purchase.additional_delivery_period_deadline"] = additional_deadline
    for key, value in facts.items():
        _fact(client, case_id, key, value)
    return case_id


def _set_spain_day(monkeypatch, value: date) -> None:
    monkeypatch.setattr("app.analysis_clock_policy.spain_today", lambda: value)
    monkeypatch.setattr("app.wait_resume.spain_today", lambda: value)


def _count(db, model, case_id: str) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id)) or 0


def test_every_wait_action_has_an_explicit_resume_contract():
    evaluator_waits = {
        action
        for evaluator in svc.EVALUATORS.values()
        for action in _ACTION_LITERAL.findall(inspect.getsource(evaluator))
        if action_kind(action) == "wait"
    }
    assert evaluator_waits == set(known_resumable_wait_actions()), (
        "Every temporal WAIT action must declare a safe re-entry contract. "
        f"evaluator={sorted(evaluator_waits)}, registered={sorted(known_resumable_wait_actions())}"
    )


def test_wait_recheck_before_milestone_is_zero_mutation(client, db, monkeypatch):
    _set_spain_day(monkeypatch, date(2026, 9, 17))
    case_id = _c04_case(client, order_date="2026-08-19")  # default due date: 2026-09-18

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "WAIT_UNTIL_DELIVERY_DUE"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    before = {
        "decision": case.current_decision_id,
        "action": case.current_action_id,
        "decisions": _count(db, Decision, case_id),
        "actions": _count(db, Action, case_id),
        "events": _count(db, AuditEvent, case_id),
    }

    response = client.post(f"/api/cases/{case_id}/resume-wait")
    assert response.status_code == 409
    assert "not elapsed" in response.json()["detail"]

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "DIAGNOSED"
    assert case.current_decision_id == before["decision"]
    assert case.current_action_id == before["action"]
    assert _count(db, Decision, case_id) == before["decisions"]
    assert _count(db, Action, case_id) == before["actions"]
    assert _count(db, AuditEvent, case_id) == before["events"]
    assert db.get(Action, before["action"]).status == "OPEN"


def test_wait_recheck_after_delivery_due_resumes_motor(client, db, monkeypatch):
    _set_spain_day(monkeypatch, date(2026, 9, 17))
    case_id = _c04_case(client, order_date="2026-08-18")  # default due date: 2026-09-17

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "WAIT_UNTIL_DELIVERY_DUE"
    old_action_id = diagnosis.json()["action_id"]
    old_decision_id = diagnosis.json()["decision_id"]

    _set_spain_day(monkeypatch, date(2026, 9, 18))
    resumed = client.post(f"/api/cases/{case_id}/resume-wait")
    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    assert body["next_action"] == "ASK_IF_ADDITIONAL_PERIOD_GIVEN"
    assert body["case_status"] == "NEEDS_INFORMATION"
    assert body["action_id"] != old_action_id
    assert body["decision_id"] != old_decision_id

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.current_action_id == body["action_id"]
    assert case.current_decision_id == body["decision_id"]
    assert db.get(Action, old_action_id).status == "COMPLETED"
    assert db.get(Action, old_action_id).completed_at is not None
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type.in_({
                "WAIT_MILESTONE_RECHECK_STARTED",
                "WAIT_MILESTONE_RECHECK_COMPLETED",
            }),
        )
    ).all()
    assert {event.event_type for event in events} == {
        "WAIT_MILESTONE_RECHECK_STARTED",
        "WAIT_MILESTONE_RECHECK_COMPLETED",
    }


def test_additional_delivery_wait_can_resume_into_termination(client, db, monkeypatch):
    _set_spain_day(monkeypatch, date(2026, 9, 17))
    case_id = _c04_case(
        client,
        order_date="2026-07-01",
        additional_deadline="2026-09-17",
    )

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["next_action"] == "WAIT_ADDITIONAL_DELIVERY_PERIOD"
    old_action_id = diagnosis.json()["action_id"]

    _set_spain_day(monkeypatch, date(2026, 9, 18))
    resumed = client.post(f"/api/cases/{case_id}/resume-wait")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["next_action"] == "PREPARE_NON_DELIVERY_TERMINATION"
    assert resumed.json()["case_status"] == "DIAGNOSED"

    db.expire_all()
    assert db.get(Action, old_action_id).status == "COMPLETED"
