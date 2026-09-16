from sqlalchemy import select

from app.models import Action, AuditEvent, Case, Outcome


def _fact(client, case_id: str, key: str, value, *, user_confirmed: bool = True):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": key,
            "value": value,
            "state": "confirmed",
            "user_confirmed": user_confirmed,
        },
    )
    assert response.status_code == 200, response.text


def _c05_refunded_case(client, *, refund_confirmed: bool = True) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Compré unos auriculares por internet, desistí y quiero comprobar el reembolso"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "C05"

    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": "2026-09-01",
        "purchase.amount_paid": 100.0,
        "purchase.premium_delivery_extra": 0.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-09-05",
        "purchase.refund_received": True,
    }
    for key, value in facts.items():
        _fact(client, case_id, key, value)
    _fact(
        client,
        case_id,
        "purchase.refund_received_amount",
        100.0,
        user_confirmed=refund_confirmed,
    )
    return case_id


def test_confirmed_complete_c05_refund_closes_case_with_traceable_outcome(client, db):
    case_id = _c05_refunded_case(client)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["next_action"] == "VERIFY_AND_CLOSE_WITHDRAWAL"
    assert body["rule_result"] == "SATISFIED"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "RESOLVED"
    assert case.current_action_id is None
    assert case.closed_at is not None

    action = db.get(Action, body["action_id"])
    assert action is not None
    assert action.type == "VERIFY_AND_CLOSE_WITHDRAWAL"
    assert action.status == "COMPLETED"
    assert action.completed_at is not None

    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert outcome is not None
    assert outcome.result_type == "FAVORABLE"
    assert outcome.amount_recovered == 100.0
    assert outcome.verified_by_user is True
    assert outcome.resolved_at is not None
    assert outcome.resolved_on is None
    assert outcome.resolution_channel is None

    terminal_event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "TERMINAL_FACT_RESOLUTION_RECORDED",
        )
    )
    assert terminal_event is not None
    assert terminal_event.payload_json["terminal_action"] == "VERIFY_AND_CLOSE_WITHDRAWAL"
    assert terminal_event.payload_json["amount_recovered"] == 100.0
    assert terminal_event.payload_json["resolved_on"] is None
    assert terminal_event.payload_json["resolution_channel"] is None

    replay = client.post(f"/api/cases/{case_id}/diagnose")
    assert replay.status_code == 422


def test_c05_refund_without_user_confirmation_does_not_auto_close(client, db):
    case_id = _c05_refunded_case(client, refund_confirmed=False)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["next_action"] == "VERIFY_AND_CLOSE_WITHDRAWAL"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "DIAGNOSED"
    assert case.closed_at is None
    assert case.current_action_id == body["action_id"]

    action = db.get(Action, body["action_id"])
    assert action is not None
    assert action.status == "OPEN"
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "TERMINAL_FACT_RESOLUTION_RECORDED",
        )
    ) is None
