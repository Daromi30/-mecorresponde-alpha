from app.models import Action, Case
from app.reviews import HumanReview


ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_structured_review_completion_closes_prior_review_action_and_reanalyzes(client, db):
    case = Case(
        status="HUMAN_REVIEW",
        vertical="electricity",
        family="E02-A",
        title="Structured review action completion",
    )
    db.add(case)
    db.flush()
    review = HumanReview(
        case_id=case.id,
        reason="MATERIAL_FACT_REVIEW",
        priority="HIGH",
        status="OPEN",
        context_json={"source": "test"},
    )
    db.add(review)
    db.flush()
    action = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="OPEN",
        payload_json={"review_id": review.id, "reason": review.reason},
    )
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    db.commit()

    resolved = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Dato material verificado; el Motor debe reanalizar ahora.",
            "fact_updates": [{
                "key": "electricity.billing.correct_amount",
                "value": 80.0,
                "state": "confirmed",
                "materiality": "critical",
                "note": "Importe comprobado manualmente.",
            }],
        },
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["review_status"] == "COMPLETED"
    assert body["updated_diagnosis"] is not None
    assert body["case_status"] != "REANALYZING"

    db.expire_all()
    stored_review = db.get(HumanReview, review.id)
    stored_action = db.get(Action, action.id)
    stored_case = db.get(Case, case.id)
    assert stored_review is not None and stored_review.status == "COMPLETED"
    assert stored_review.completed_at is not None
    assert stored_action is not None and stored_action.status == "COMPLETED"
    assert stored_action.completed_at is not None
    assert stored_case is not None
    assert stored_case.current_action_id != action.id
    next_action = db.get(Action, stored_case.current_action_id)
    assert next_action is not None
    assert next_action.status in {"OPEN", "READY"}
