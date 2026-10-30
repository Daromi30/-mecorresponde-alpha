"""RB-028: material mutations cannot release or export stale derivatives."""

from sqlalchemy import select

from app import services_v2 as svc
from app.account_export import build_account_export
from app.auth_models import User
from app.models import Action, AuditEvent, Case, Decision
from app.reviews import HumanReview
from app.routers.cases_v2 import serialize_case


def test_material_mutation_invalidates_decision_action_and_review_and_hides_them_from_export(db):
    user = User(email="rb028-user@example.com", password_hash="synthetic")
    db.add(user)
    db.flush()
    case = Case(
        user_id=user.id,
        status="READY_TO_SUBMIT",
        vertical="electricity",
        family="E02-A",
        title="Synthetic RB-028 case",
        raw_intake="Synthetic intake only",
    )
    db.add(case)
    db.flush()
    decision = Decision(
        case_id=case.id,
        viability="HIGH",
        economic_value=40,
        claimable_amount=40,
        worth_pursuing="YES",
        reasoning_summary="Synthetic stale decision",
    )
    action = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        status="READY",
        payload_json={"text": "Synthetic stale draft"},
    )
    review = HumanReview(
        case_id=case.id,
        reason="MATERIAL_FACT_REVIEW",
        status="OPEN",
        context_json={"synthetic": True},
    )
    db.add_all([decision, action, review])
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id
    db.commit()

    svc.upsert_fact(
        db,
        case,
        "electricity.billing.correct_amount",
        20,
        state="confirmed",
        user_confirmed=True,
        created_by="user",
    )

    db.expire_all()
    case = db.get(Case, case.id)
    decision = db.get(Decision, decision.id)
    action = db.get(Action, action.id)
    review = db.get(HumanReview, review.id)
    assert case.current_decision_id is None and case.current_action_id is None
    assert case.status == "INTAKE"
    assert decision.invalidated_at is not None
    assert action.status == "SUPERSEDED" and action.completed_at is not None
    assert review.status == "SUPERSEDED" and review.completed_at is not None

    public = serialize_case(db, case)
    assert public["decisions"] == []
    assert public["actions"] == []
    assert public["human_reviews"] == []
    exported = build_account_export(db, user)["cases"][0]
    assert exported["decisions"] == []
    assert exported["actions"] == []
    assert exported["human_reviews"] == []

    internal = serialize_case(db, case, internal=True)
    assert internal["decisions"][0]["invalidated_at"] is not None
    assert internal["actions"][0]["status"] == "SUPERSEDED"
    assert internal["human_reviews"][0]["status"] == "SUPERSEDED"
    event = db.scalar(select(AuditEvent).where(
        AuditEvent.case_id == case.id,
        AuditEvent.event_type == "DERIVED_OUTPUTS_INVALIDATED",
    ))
    assert event is not None
    assert event.payload_json["decision_ids"] == [decision.id]
    assert "Synthetic stale decision" not in str(event.payload_json)


def test_unknown_decision_state_is_fail_closed_in_public_surfaces(db):
    case = Case(
        status="INTAKE",
        vertical="purchases",
        family="C01",
        raw_intake="Synthetic inconsistent pointer",
        current_decision_id="missing-decision",
    )
    db.add(case)
    db.commit()
    public = serialize_case(db, case)
    assert public["current_decision_id"] is None
    assert public["decisions"] == []
