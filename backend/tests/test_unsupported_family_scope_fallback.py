import pytest
from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Decision, Outcome
from app.reviews import HumanReview


FAMILY_MESSAGES = (
    ("C01", "Compré un televisor en una tienda, está defectuoso y me rechazan la garantía"),
    ("C02", "Compré un portátil, ya lo repararon y volvió a fallar"),
    ("C03", "Compré un móvil y me enviaron otro modelo distinto a lo anunciado"),
    ("C04", "Compré una cafetera online y no me ha llegado el pedido"),
    ("C05", "Compré unos auriculares online y quiero devolver la compra dentro de 14 días"),
)


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _count(db, model, case_id: str) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id)) or 0


@pytest.mark.parametrize(("family", "message"), FAMILY_MESSAGES)
def test_known_purchase_family_outside_consumer_scope_routes_to_protected_review(
    client,
    db,
    family: str,
    message: str,
):
    created = client.post("/api/cases", json={"message": message})
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == family

    _fact(client, case_id, "purchase.buyer_is_consumer", False)
    _fact(client, case_id, "purchase.seller_is_business", True)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "OUT_OF_SCOPE"
    assert body["scope_status"] == "UNSUPPORTED"
    assert body["next_action"] == "REDIRECT_NON_CONSUMER_PURCHASE"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "HUMAN_REVIEW"
    assert case.closed_at is None
    assert case.current_decision_id == body["decision_id"]
    assert case.current_action_id == body["action_id"]

    source = db.scalars(
        select(Action).where(
            Action.case_id == case_id,
            Action.type == "REDIRECT_NON_CONSUMER_PURCHASE",
        )
    ).one()
    assert source.status == "COMPLETED"
    assert source.completed_at is not None

    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    assert current.payload_json["reason"] == "ENGINE_UNSUPPORTED_SCOPE"
    assert current.payload_json["requested_action"] == "REDIRECT_NON_CONSUMER_PURCHASE"

    review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "ENGINE_UNSUPPORTED_SCOPE",
            HumanReview.status == "OPEN",
        )
    ).one()
    assert review.context_json["family"] == family
    assert review.context_json["source_decision_id"] == body["decision_id"]
    assert review.context_json["source_action_id"] == source.id

    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "ENGINE_UNSUPPORTED_SCOPE_REVIEW_REQUIRED",
        )
    ).one()
    assert event.payload_json["family"] == family
    assert event.payload_json["source_action_id"] == source.id
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None

    before = {
        "decisions": _count(db, Decision, case_id),
        "actions": _count(db, Action, case_id),
        "reviews": _count(db, HumanReview, case_id),
        "events": db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.case_id == case_id,
                AuditEvent.event_type == "ENGINE_UNSUPPORTED_SCOPE_REVIEW_REQUIRED",
            )
        ),
    }
    replay = client.post(f"/api/cases/{case_id}/diagnose")
    assert replay.status_code == 409
    db.expire_all()
    assert db.get(Case, case_id).status == "HUMAN_REVIEW"
    assert _count(db, Decision, case_id) == before["decisions"]
    assert _count(db, Action, case_id) == before["actions"]
    assert _count(db, HumanReview, case_id) == before["reviews"]
    assert db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "ENGINE_UNSUPPORTED_SCOPE_REVIEW_REQUIRED",
        )
    ) == before["events"]
