from datetime import date, timedelta

from sqlalchemy import select

from app import analysis_clock_policy, services_v2 as svc
from app.models import Fact


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _c04_case(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["family"] == "C04"
    return created.json()["id"]


def test_analysis_date_uses_spain_clock_without_persisting_a_fact(client, db, monkeypatch):
    case_id = _c04_case(client)
    monkeypatch.setattr(analysis_clock_policy, "spain_today", lambda: date(2026, 9, 18))

    facts = svc.latest_facts(db, case_id)
    analysis_date = facts["system.analysis_date"]
    assert analysis_date.value == "2026-09-18"
    assert analysis_date.state == "confirmed"
    assert analysis_date.user_confirmed is False
    assert db.scalar(
        select(Fact).where(Fact.case_id == case_id, Fact.key == "system.analysis_date")
    ) is None


def test_c04_diagnosis_and_guided_question_share_spain_analysis_date(client, monkeypatch):
    # Model the midnight edge explicitly: Madrid is already tomorrow while a UTC server
    # can still be on today. The default 30-day delivery period ends on server_today, so
    # only the Spain civil date says that the period has actually expired.
    server_today = date.today()
    madrid_today = server_today + timedelta(days=1)
    order_date = server_today - timedelta(days=30)
    monkeypatch.setattr(analysis_clock_policy, "spain_today", lambda: madrid_today)

    case_id = _c04_case(client)
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": order_date.isoformat(),
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
    }.items():
        _fact(client, case_id, key, value)

    question = client.get(f"/api/cases/{case_id}/next-question")
    assert question.status_code == 200, question.text
    assert question.json()["field"] == "purchase.additional_delivery_period_requested"
    assert question.json()["input_type"] == "boolean"

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["next_action"] == "ASK_IF_ADDITIONAL_PERIOD_GIVEN"
    assert body["rule_result"] == "APPLIES_DELIVERY_OVERDUE"
    assert body["missing_facts"] == ["purchase.additional_delivery_period_requested"]
