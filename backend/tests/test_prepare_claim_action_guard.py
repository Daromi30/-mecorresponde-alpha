from sqlalchemy import func, select

from app.models import Action, Case


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _c04_case(client, *, order_date: str, additional_requested=None) -> str:
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
    if additional_requested is not None:
        facts["purchase.additional_delivery_period_requested"] = additional_requested
    for key, value in facts.items():
        _fact(client, case_id, key, value)
    return case_id


def _submit_action_count(db, case_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(Action).where(
            Action.case_id == case_id,
            Action.type == "SUBMIT_INITIAL_CLAIM",
        )
    ) or 0


def test_wait_action_cannot_be_packaged_as_an_outbound_claim(client, db):
    case_id = _c04_case(client, order_date="2026-09-01")
    diagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosed.status_code == 200, diagnosed.text
    assert diagnosed.json()["next_action"] == "WAIT_UNTIL_DELIVERY_DUE"
    old_action_id = diagnosed.json()["action_id"]

    blocked = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert blocked.status_code == 409
    assert "does not permit" in blocked.json()["detail"]

    db.expire_all()
    case = db.get(Case, case_id)
    action = db.get(Action, old_action_id)
    assert case is not None and case.status == "DIAGNOSED"
    assert case.current_action_id == old_action_id
    assert action is not None and action.status == "OPEN"
    assert _submit_action_count(db, case_id) == 0


def test_true_prepare_action_can_still_create_ready_package(client, db):
    case_id = _c04_case(
        client,
        order_date="2026-07-01",
        additional_requested=False,
    )
    diagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosed.status_code == 200, diagnosed.text
    assert diagnosed.json()["next_action"] == "GIVE_ADDITIONAL_DELIVERY_PERIOD"

    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, prepared.text

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None and case.status == "READY_TO_SUBMIT"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "SUBMIT_INITIAL_CLAIM"
    assert current.status == "READY"
    assert _submit_action_count(db, case_id) == 1


def test_ready_package_reprepare_is_idempotent(client, db):
    case_id = _c04_case(
        client,
        order_date="2026-07-01",
        additional_requested=False,
    )
    diagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosed.status_code == 200, diagnosed.text

    first = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert first.status_code == 200, first.text
    first_action_id = first.json()["action_id"]

    second = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert second.status_code == 200, second.text
    assert second.json()["action_id"] == first_action_id

    db.expire_all()
    assert _submit_action_count(db, case_id) == 1
