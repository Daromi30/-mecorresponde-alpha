from sqlalchemy import func, select

from app.models import Action
from app.reviews import HumanReview


ADMIN = {"Authorization": "Bearer test-admin-token"}


def _professional_review(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    case_id = created.json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        assert client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        ).status_code == 200
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
        json={"submitted_on": "2026-09-10", "channel": "web_form"},
    ).status_code == 200
    partial = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos una parte de la reclamación, pero rechazamos el resto.",
            "received_on": "2026-09-12",
            "channel": "email",
        },
    )
    assert partial.status_code == 200, partial.text

    db.expire_all()
    post_review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert post_review is not None
    escalated = client.post(
        f"/api/admin/reviews/{post_review.id}/escalate-professional",
        headers=ADMIN,
        json={"reviewer_decision": "Requiere criterio profesional para el siguiente escalado."},
    )
    assert escalated.status_code == 200, escalated.text
    professional_id = escalated.json()["professional_review_id"]
    return case_id, professional_id


def test_professional_structured_fact_cannot_reopen_initial_claim(client, db):
    case_id, review_id = _professional_review(client, db)

    resolved = client.post(
        f"/api/admin/reviews/{review_id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Se verifica un dato contextual sin decidir la vía jurídica.",
            "fact_updates": [{
                "key": "review.professional_context_checked",
                "value": True,
                "state": "confirmed",
                "materiality": "context",
            }],
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["case_status"] == "HUMAN_REVIEW"

    db.expire_all()
    open_escalation = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert open_escalation is not None

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
