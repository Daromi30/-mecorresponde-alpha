from sqlalchemy import select

from app.models import Action, AuditEvent, Case
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}


def _submitted_e04b(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        response = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200, response.text
    assert client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    ).status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-10", "channel": "web_form", "reference_number": "INITIAL-1"},
    ).status_code == 200
    return case_id


def _open_post_response_review(client, db):
    case_id = _submitted_e04b(client)
    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos una parte de la reclamación, pero rechazamos el resto.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "PARTIAL-1",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["type"] == "PARTIAL"
    db.expire_all()
    review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert review is not None
    return case_id, review


def test_post_response_review_can_be_handed_to_professional_without_inventing_route(client, db):
    case_id, review = _open_post_response_review(client, db)

    response = client.post(
        f"/api/admin/reviews/{review.id}/escalate-professional",
        headers=ADMIN,
        json={
            "reviewer_decision": "El siguiente escalado jurídico requiere revisión profesional del expediente completo."
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "COMPLETED"
    assert body["case_status"] == "HUMAN_REVIEW"
    assert body["phase"] == "PROFESSIONAL_REVIEW"
    assert body["professional_review_id"]
    assert body["action_id"]

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.id == body["action_id"]
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    assert current.payload_json == {
        "reason": "PROFESSIONAL_ESCALATION_REQUIRED",
        "review_id": body["professional_review_id"],
        "phase": "PROFESSIONAL_REVIEW",
        "decision_id": case.current_decision_id,
    }

    original = db.get(HumanReview, review.id)
    professional = db.get(HumanReview, body["professional_review_id"])
    assert original is not None and original.status == "COMPLETED"
    assert professional is not None and professional.status == "OPEN"
    assert professional.reason == "PROFESSIONAL_ESCALATION_REQUIRED"
    assert professional.priority == "HIGH"
    assert professional.context_json["source_review_id"] == review.id
    assert professional.context_json["phase"] == "PROFESSIONAL_REVIEW"

    audit = db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "PROFESSIONAL_ESCALATION_REQUIRED",
        )
    )
    assert audit is not None
    serialized = str(audit.payload_json).lower()
    for prohibited in (
        "court",
        "tribunal",
        "arbit",
        "regulator",
        "authority",
        "deadline",
        "success_probability",
        "legal_basis",
    ):
        assert prohibited not in serialized


def test_professional_handoff_rejects_non_post_response_reviews(client, db):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    review = create_human_review(
        db,
        case,
        reason="MATERIAL_FACT_REVIEW",
        priority="HIGH",
        context={"source": "test"},
    )
    db.commit()
    db.refresh(review)

    blocked = client.post(
        f"/api/admin/reviews/{review.id}/escalate-professional",
        headers=ADMIN,
        json={"reviewer_decision": "No corresponde esta vía."},
    )
    assert blocked.status_code == 409
    db.expire_all()
    assert db.get(HumanReview, review.id).status == "OPEN"


def test_professional_handoff_requires_admin(client, db):
    _, review = _open_post_response_review(client, db)
    blocked = client.post(
        f"/api/admin/reviews/{review.id}/escalate-professional",
        json={"reviewer_decision": "Intento sin autorización"},
    )
    assert blocked.status_code == 401
