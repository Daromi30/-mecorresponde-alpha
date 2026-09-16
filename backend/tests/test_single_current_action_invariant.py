from sqlalchemy import select

from app.case_lifecycle import set_current_action
from app.models import Action, Case


def test_setting_next_current_action_completes_previous_pending_action(db):
    case = Case(
        status="HUMAN_REVIEW",
        vertical="electricity",
        family="E04-B",
        title="Single current action invariant",
    )
    db.add(case)
    db.flush()

    previous = Action(
        case_id=case.id,
        type="HUMAN_REVIEW",
        status="OPEN",
        payload_json={"review_id": "review-old"},
    )
    db.add(previous)
    db.flush()
    case.current_action_id = previous.id
    db.commit()

    following = set_current_action(
        db,
        case,
        "HUMAN_REVIEW",
        payload={"review_id": "review-new"},
    )
    db.commit()

    db.expire_all()
    old = db.get(Action, previous.id)
    current = db.get(Action, following.id)
    refreshed_case = db.get(Case, case.id)

    assert old is not None
    assert old.status == "COMPLETED"
    assert old.completed_at is not None
    assert current is not None
    assert current.status == "OPEN"
    assert refreshed_case is not None
    assert refreshed_case.current_action_id == current.id

    pending = db.scalars(
        select(Action).where(
            Action.case_id == case.id,
            Action.status.in_(("OPEN", "READY")),
        )
    ).all()
    assert [row.id for row in pending] == [current.id]
