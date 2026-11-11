"""HTTP regression: future case modes inherit no participant output authority."""

from datetime import date

from sqlalchemy import select

from app.auth_models import User
from app.models import (
    Action,
    AuditEvent,
    Calculation,
    Case,
    Communication,
    Deadline,
    Decision,
    Fact,
    LegalRuleVersion,
    RuleEvaluation,
)
from app.reviews import HumanReview


def _future_mode_case(client, db) -> str:
    email = "future-mode-owner@example.com"
    client.historical_account(email, "synthetic-future-mode-password")
    user = db.scalar(select(User).where(User.email == email))
    rule = db.scalar(select(LegalRuleVersion).order_by(LegalRuleVersion.rule_id.asc()))

    case = Case(
        user_id=user.id,
        mode="FUTURE_UNAPPROVED_MODE",
        status="DIAGNOSED",
        vertical="electricity",
        family="E04-B",
        title="Fictional future-mode case",
        raw_intake="Fictional future-mode input",
    )
    db.add(case)
    db.flush()
    db.add_all([
        Fact(
            case_id=case.id,
            key="fictional.user_fact",
            value_json={"value": "participant supplied"},
            state="confirmed",
            user_confirmed=True,
            created_by="user",
        ),
        Fact(
            case_id=case.id,
            key="fictional.derived_fact",
            value_json={"value": "must remain internal"},
            state="asserted",
            created_by="human",
        ),
    ])
    evaluation = RuleEvaluation(
        case_id=case.id,
        rule_version_id=rule.id,
        facts_snapshot={"fictional.user_fact": {"value": "participant supplied"}},
        result="APPLIES",
    )
    calculation = Calculation(
        case_id=case.id,
        type="fictional_calculation",
        inputs_json={"amount": 120},
        formula_version="fictional-1",
        result=40,
        explanation="Fictional derived amount that must remain internal.",
    )
    db.add_all([evaluation, calculation])
    db.flush()
    decision = Decision(
        case_id=case.id,
        viability="HIGH",
        claimable_amount=40,
        economic_value=120,
        worth_pursuing="YES",
        reasoning_summary="Fictional unapproved legal conclusion.",
        rule_evaluations_json=[{
            "rule_evaluation_id": evaluation.id,
            "rule_id": rule.rule_id,
            "version": rule.version,
            "result": "APPLIES",
            "calculation_id": calculation.id,
        }],
    )
    action = Action(
        case_id=case.id,
        type="SUBMIT_INITIAL_CLAIM",
        payload_json={"claimable_amount": 40, "draft": "fictional unapproved action"},
    )
    db.add_all([decision, action])
    db.flush()
    case.current_decision_id = decision.id
    case.current_action_id = action.id
    db.add_all([
        Deadline(
            case_id=case.id,
            deadline_type="FICTIONAL_DEADLINE",
            trigger_event="FICTIONAL_EVENT",
            trigger_date=date(2026, 1, 1),
            computed_date=date(2026, 1, 15),
        ),
        HumanReview(
            case_id=case.id,
            reason="FICTIONAL_INTERNAL_REVIEW",
            context_json={"decision_id": decision.id},
        ),
        AuditEvent(
            case_id=case.id,
            event_type="DIAGNOSIS_GENERATED",
            payload_json={"decision_id": decision.id},
        ),
        Communication(
            case_id=case.id,
            direction="OUTBOUND",
            channel="fictional",
            body="Fictional unapproved claim text.",
        ),
    ])
    db.commit()
    return case.id


def test_unknown_mode_http_surfaces_fail_closed_and_keep_user_facts(client, db):
    case_id = _future_mode_case(client, db)

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["release_status"] == "BLOCKED_UNRECOGNIZED_MODE"
    assert body["current_decision_id"] is None and body["current_action_id"] is None
    assert body["decisions"] == body["actions"] == body["deadlines"] == []
    assert body["evidence"] == body["human_reviews"] == []
    assert [fact["key"] for fact in body["facts"]] == ["fictional.user_fact"]
    assert "Fictional unapproved legal conclusion" not in detail.text
    assert "fictional unapproved action" not in detail.text

    exported = client.get("/api/auth/export")
    assert exported.status_code == 200
    exported_case = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    assert exported_case["release_status"] == "BLOCKED_UNRECOGNIZED_MODE"
    assert [fact["key"] for fact in exported_case["facts"]] == ["fictional.user_fact"]
    for field in (
        "evidence", "documents", "decisions", "actions", "deadlines", "communications",
        "outcomes", "counterarguments", "calculations", "rule_evaluations", "human_reviews",
        "audit_events", "ai_runs",
    ):
        assert exported_case[field] == []

    assert client.get(f"/api/cases/{case_id}/legal-sources").json() == {
        "decision_id": None,
        "sources": [],
    }
    quality = client.get(f"/api/cases/{case_id}/quality")
    assert quality.status_code == 200
    assert quality.json()["gates"]["current_decision_id"] is None
    assert quality.json()["gates"]["rules_evaluated"] == 0
    timeline = client.get(f"/api/cases/{case_id}/timeline")
    assert timeline.status_code == 200
    assert [event["type"] for event in timeline.json()["events"]] == ["CASE_OPENED"]
    assert client.get(f"/api/cases/{case_id}/communications").json() == {
        "case_id": case_id,
        "communications": [],
    }
    assert client.get(f"/api/cases/{case_id}/reviews").json() == []


def test_unknown_mode_http_actions_fail_before_substantive_processing(client, db):
    case_id = _future_mode_case(client, db)
    requests = [
        client.get(f"/api/cases/{case_id}/handoff"),
        client.post(f"/api/cases/{case_id}/prepare-claim"),
        client.post(f"/api/cases/{case_id}/submission", json={"submitted_on": "2026-01-02"}),
        client.post(f"/api/cases/{case_id}/responses", json={"text": "Fictional response"}),
        client.post(f"/api/cases/{case_id}/responses/evidenced", json={
            "text": "Fictional response", "received_on": "2026-01-03", "channel": "email",
        }),
        client.post(f"/api/cases/{case_id}/outcome", json={
            "result_type": "FAVORABLE", "verified_by_user": False,
        }),
        client.post(f"/api/cases/{case_id}/outcome/evidenced", json={
            "result_type": "FAVORABLE", "verified_by_user": False,
            "remaining_material_commitments": "unknown",
        }),
        client.post(f"/api/cases/{case_id}/resume-wait"),
    ]
    assert all(response.status_code == 409 for response in requests)
    assert all(
        "Substantive legal output is not approved" in response.json()["detail"]
        for response in requests
    )
