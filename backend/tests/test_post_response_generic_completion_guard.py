from app.models import Case
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}


def _open_review(db, reason: str):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    review = create_human_review(
        db,
        case,
        reason=reason,
        priority="HIGH",
        context={"phase": "test"},
    )
    db.commit()
    db.refresh(case)
    db.refresh(review)
    return case, review


def test_generic_completion_cannot_close_post_response_escalation(client, db):
    case, review = _open_review(db, "POST_DENIAL_ESCALATION_REVIEW")

    blocked = client.post(
        f"/api/admin/reviews/{review.id}/complete",
        headers=ADMIN,
        json={"reviewer_decision": "Cerrar con una nota genérica"},
    )

    assert blocked.status_code == 409
    assert "generic note" in blocked.json()["detail"]
    db.expire_all()
    stored_review = db.get(HumanReview, review.id)
    stored_case = db.get(Case, case.id)
    assert stored_review is not None and stored_review.status == "OPEN"
    assert stored_review.reviewer_decision is None
    assert stored_review.completed_at is None
    assert stored_case is not None and stored_case.status == "HUMAN_REVIEW"


def test_generic_completion_cannot_close_professional_handoff(client, db):
    case, review = _open_review(db, "PROFESSIONAL_ESCALATION_REQUIRED")

    blocked = client.post(
        f"/api/admin/reviews/{review.id}/complete",
        headers=ADMIN,
        json={"reviewer_decision": "Dar por terminada la revisión profesional sin ruta explícita"},
    )

    assert blocked.status_code == 409
    assert "professional-review workflow" in blocked.json()["detail"]
    db.expire_all()
    stored_review = db.get(HumanReview, review.id)
    stored_case = db.get(Case, case.id)
    assert stored_review is not None and stored_review.status == "OPEN"
    assert stored_review.reviewer_decision is None
    assert stored_case is not None and stored_case.status == "HUMAN_REVIEW"
