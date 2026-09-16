import pytest
from sqlalchemy import select

from app.case_lifecycle import complete_current_action
from app.models import Action, Case
from app.reviews import HumanReview


ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.mark.parametrize(
    ("review_reason", "action_type"),
    [
        ("MATERIAL_FACT_REVIEW", "HUMAN_REVIEW"),
        ("HUMAN_REVIEW_LEGACY", "HUMAN_REVIEW_LEGACY"),
        ("HUMAN_REVIEW_SECOND_HAND", "HUMAN_REVIEW_SECOND_HAND"),
    ],
)
def test_structured_review_completion_closes_prior_review_action_and_reanalyzes(
    client,
    db,
    review_reason,
    action_type,
):
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
        reason=review_reason,
        priority="HIGH",
        status="OPEN",
        context_json={"source": "test"},
    )
    db.add(review)
    db.flush()
    action = Action(
        case_id=case.id,
        type=action_type,
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

    pending = db.scalars(
        select(Action).where(
            Action.case_id == case.id,
            Action.status.in_(("OPEN", "READY")),
        )
    ).all()
    assert [row.id for row in pending] == [next_action.id]


def test_human_review_filter_does_not_close_unrelated_current_action(db):
    case = Case(
        status="HUMAN_REVIEW",
        vertical="electricity",
        family="E02-A",
        title="Review action filter",
    )
    db.add(case)
    db.flush()
    action = Action(
        case_id=case.id,
        type="WAIT_FOR_RESPONSE",
        status="OPEN",
        payload_json={},
    )
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    db.commit()

    assert complete_current_action(db, case, only_types={"HUMAN_REVIEW"}) is None
    db.commit()
    db.refresh(action)
    assert action.status == "OPEN"
    assert action.completed_at is None
