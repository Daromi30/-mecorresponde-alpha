from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case
from app.reviews import HumanReview


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
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    )
    assert charges.status_code == 200, charges.text
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-10", "channel": "web_form", "reference_number": "INITIAL-1"},
    )
    assert submitted.status_code == 200, submitted.text
    return case_id


def test_structured_post_response_review_preserves_escalation_guard(client, db):
    case_id = _submitted_e04b(client)
    partial = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos una parte de la reclamación, pero rechazamos el resto.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "PARTIAL-1",
        },
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["analysis"]["type"] == "PARTIAL"
    assert partial.json()["case_status"] == "HUMAN_REVIEW"

    db.expire_all()
    original_review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert original_review is not None

    resolved = client.post(
        f"/api/admin/reviews/{original_review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Se confirma un dato contextual, pero no cambia el fundamento del expediente.",
            "fact_updates": [{
                "key": "review.post_response_context_checked",
                "value": True,
                "state": "confirmed",
                "materiality": "context",
                "note": "Dato contextual revisado por una persona.",
            }],
        },
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["review_status"] == "COMPLETED"
    assert body["updated_diagnosis"] is not None
    assert body["case_status"] == "HUMAN_REVIEW"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    assert current.payload_json.get("phase") == "POST_RESPONSE_ESCALATION"

    assert db.get(HumanReview, original_review.id).status == "COMPLETED"
    followup = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert followup is not None
    assert followup.id != original_review.id

    ready_initial = db.scalar(
        select(func.count())
        .select_from(Action)
        .where(
            Action.case_id == case_id,
            Action.type == "SUBMIT_INITIAL_CLAIM",
            Action.status == "READY",
        )
    )
    assert int(ready_initial or 0) == 0

    submissions = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    )
    assert int(submissions or 0) == 1
