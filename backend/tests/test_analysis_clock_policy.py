from datetime import date

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


def test_c04_due_date_uses_spain_analysis_date_not_server_local_date(client, monkeypatch):
    # The contractual default due date is 30 calendar days after this order: 2026-09-17.
    # By forcing the jurisdiction clock to 2026-09-18 we prove that diagnosis reads the
    # injected system.analysis_date instead of services_v2's server-local date fallback.
    monkeypatch.setattr(analysis_clock_policy, "spain_today", lambda: date(2026, 9, 18))
    case_id = _c04_case(client)
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
    body = diagnosis.json()
    assert body["next_action"] == "ASK_IF_ADDITIONAL_PERIOD_GIVEN"
    assert body["rule_result"] == "APPLIES_DELIVERY_OVERDUE"
    assert body["missing_facts"] == ["purchase.additional_delivery_period_requested"]
