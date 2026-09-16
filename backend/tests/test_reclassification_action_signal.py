from sqlalchemy import select

from app.models import Action, AuditEvent, Case
from app.reviews import HumanReview


def _create(client, message: str) -> dict:
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _assert_fail_closed_review(db, case_id: str, source_action_type: str) -> None:
    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "HUMAN_REVIEW"

    source = db.scalars(
        select(Action).where(
            Action.case_id == case_id,
            Action.type == source_action_type,
        )
    ).one()
    assert source.status == "COMPLETED"
    assert source.completed_at is not None

    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    assert current.payload_json["requested_action"] == source_action_type

    review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "ENGINE_RECLASSIFICATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).one()
    assert review is not None

    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "ENGINE_RECLASSIFICATION_REVIEW_REQUIRED",
        )
    ).one()
    assert event.payload_json["requested_action"] == source_action_type
    assert event.payload_json["reason"] == "unregistered_or_same_family_transition"


def test_c03_reclassification_action_with_low_viability_fails_closed(client, db):
    created = _create(client, "Compré un móvil y me enviaron otro modelo distinto a lo anunciado")
    assert created["family"] == "C03"
    case_id = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Móvil",
        "purchase.delivery_date": "2026-09-01",
        "purchase.price": 699.0,
        "purchase.contract_description": "Modelo X Pro",
        "purchase.received_description": "Modelo X Pro",
        "purchase.mismatch_confirmed": False,
        "purchase.mismatch_material": False,
        "purchase.seller_denied_conformity": False,
    }
    for key, value in facts.items():
        _fact(client, case_id, key, value)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "LOW"
    assert diagnosis.json()["next_action"] == "RECLASSIFY_PURCHASE_ISSUE"
    _assert_fail_closed_review(db, case_id, "RECLASSIFY_PURCHASE_ISSUE")


def test_c04_delivered_order_reclassification_action_fails_closed(client, db):
    created = _create(client, "Compré una cafetera online y no me ha llegado el pedido")
    assert created["family"] == "C04"
    case_id = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": "2026-08-01",
        "purchase.amount_paid": 149.90,
        "purchase.delivered": True,
    }
    for key, value in facts.items():
        _fact(client, case_id, key, value)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "LOW"
    assert diagnosis.json()["next_action"] == "RECLASSIFY_DELIVERED_ORDER"
    _assert_fail_closed_review(db, case_id, "RECLASSIFY_DELIVERED_ORDER")


def test_c05_non_distance_reclassification_action_fails_closed(client, db):
    created = _create(client, "Compré unos auriculares online y quiero devolver la compra dentro de 14 días")
    assert created["family"] == "C05"
    case_id = created["id"]
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": False,
    }.items():
        _fact(client, case_id, key, value)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "OUT_OF_SCOPE"
    assert diagnosis.json()["next_action"] == "RECLASSIFY_NON_DISTANCE_PURCHASE"
    _assert_fail_closed_review(db, case_id, "RECLASSIFY_NON_DISTANCE_PURCHASE")
