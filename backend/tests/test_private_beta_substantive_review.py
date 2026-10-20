"""P0-10 synthetic checks. Production private-beta launch stays disabled."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth_models import ReviewerFamilyAuthorization
from app.family_manifest import FAMILY_MANIFEST
from app.models import Action, AuditEvent, Calculation, Case, Decision, Evidence, RuleEvaluation
from app.main import app
from app.private_beta_release import RELEASE_REASON, release_approved
from app.reviews import HumanReview
from app import real_beta_gate as gate
from test_private_beta_release_safety import APPROVAL, _admit, _record_required_facts


@pytest.fixture
def future_test_gate(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)
    assert gate.real_beta_gate_open() is False


def ready(client, db, family="E02-A"):
    case_id, reviewer, facts = _admit(client, db, family)
    _record_required_facts(client, case_id, facts)
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assert review is not None
    return case_id, reviewer, review


def assign(client, review, reviewer):
    response = client.post(f"/api/admin/reviews/{review.id}/assign", json={"reviewer_id": reviewer.id})
    assert response.status_code == 200, response.text


def resolve(client, review, outcome, reason, requested_fields=None):
    return client.post(f"/api/admin/reviews/{review.id}/resolve-private", json={
        "outcome": outcome, "reason_code": reason,
        "requested_fields": requested_fields or [],
    })


@pytest.mark.parametrize("family", ["E02-A", "C01"])
def test_review_context_and_explicit_unselected_checklist(client, db, future_test_gate, family):
    case_id, reviewer, review = ready(client, db, family)
    assign(client, review, reviewer)
    context = client.get(f"/api/admin/reviews/{review.id}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["case_id"] == case_id and body["family"] == family
    assert body["decision"]["id"] == db.get(Case, case_id).current_decision_id
    assert body["action"]["id"] == db.get(Case, case_id).current_action_id
    assert body["facts_version"] and body["facts"] and body["rule_evaluations"] and body["sources"]
    assert body["professional_legal_qualification"] == "NOT_ASSERTED"
    assert all("created_by" in fact and "state" in fact for fact in body["facts"])
    url = f"/api/admin/reviews/{review.id}/approve-release"
    assert client.post(url).status_code == 422
    assert client.post(url, json={"reason_code": "CONFIRMED_AS_SUPPORTED"}).status_code == 422
    assert client.post(url, json={"checklist": APPROVAL["checklist"]}).status_code == 422
    partial = {**APPROVAL, "checklist": {**APPROVAL["checklist"], "action_reviewed": False}}
    assert client.post(url, json=partial).status_code == 422
    assert client.get(f"/api/cases/{case_id}").json()["decisions"] == []


def test_scope_is_explicit_family_specific_and_revocable(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db, "C01")
    assert client.put(f"/api/admin/reviewers/{reviewer.id}/technical-scope", json={
        "families": ["E02-A"],
    }).status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/assign", json={
        "reviewer_id": reviewer.id,
    }).status_code == 422
    review.assigned_reviewer_id = reviewer.id  # Simulate a pre-existing assignment after scope revocation.
    db.commit()
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 403
    assert not release_approved(db, db.get(Case, case_id))
    assert db.scalar(select(ReviewerFamilyAuthorization.id).where(
        ReviewerFamilyAuthorization.reviewer_id == reviewer.id,
        ReviewerFamilyAuthorization.family == "C01",
    )) is None


def test_unassigned_or_wrong_reviewer_cannot_resolve(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 403
    assign(client, review, reviewer)
    other = client.post("/api/admin/reviewers", json={
        "login_id": "other-reviewer", "role": "reviewer", "initial_password": "synthetic-other-password",
    })
    assert other.status_code == 201
    assert client.put(f"/api/admin/reviewers/{other.json()['id']}/technical-scope", json={
        "families": ["E02-A"],
    }).status_code == 200
    assert client.post("/api/backoffice-auth/logout").status_code == 200
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": "other-reviewer", "password": "synthetic-other-password",
    }).status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 403
    assert resolve(client, review, "ESCALATE", "LEGAL_UNCERTAINTY").status_code == 403
    assert client.get(f"/api/admin/reviews/{review.id}/context").status_code == 403
    assert not release_approved(db, db.get(Case, case_id))


def test_information_request_cannot_introduce_free_text_or_unlisted_field(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db, "C01")
    assign(client, review, reviewer)
    for field in ("purchase.product_name", "purchase.defect_description", "purchase.other_text"):
        assert resolve(client, review, "REQUEST_INFORMATION", "INSUFFICIENT_INFORMATION", [field]).status_code == 422
    assert resolve(client, review, "REQUEST_INFORMATION", "ACTION_BLOCKED", ["purchase.price"]).status_code == 422
    assert db.get(HumanReview, review.id).status == "OPEN"
    assert not release_approved(db, db.get(Case, case_id))


@pytest.mark.parametrize("outcome,reason,field,status", [
    ("REQUEST_INFORMATION", "INSUFFICIENT_INFORMATION", "electricity.billing.invoice_date", "NEEDS_INFORMATION"),
    ("REJECT_DIAGNOSIS", "DIAGNOSIS_REJECTED", None, "HUMAN_REVIEW"),
    ("BLOCK_ACTION", "ACTION_BLOCKED", None, "HUMAN_REVIEW"),
    ("ESCALATE", "LEGAL_UNCERTAINTY", None, "HUMAN_REVIEW"),
])
def test_nonapproval_outcomes_block_release(client, db, future_test_gate, outcome, reason, field, status):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    prior_action = db.get(Action, db.get(Case, case_id).current_action_id)
    response = resolve(client, review, outcome, reason, [field] if field else [])
    assert response.status_code == 200, response.text
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.status == status and not release_approved(db, case)
    assert db.get(Action, prior_action.id).status == "SUPERSEDED"
    assert client.get(f"/api/cases/{case_id}").json()["decisions"] == []
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 409
    event = db.scalar(select(AuditEvent).where(
        AuditEvent.case_id == case_id, AuditEvent.event_type == "PRIVATE_BETA_REVIEW_RESOLVED",
    ))
    assert event.payload_json["reason_code"] == reason
    assert "facts" not in event.payload_json and "reasoning_summary" not in event.payload_json
    if field:
        question = client.get(f"/api/cases/{case_id}/next-question").json()
        assert question["field"] == field and question["phase"] == "INFORMATION_REQUEST"


def test_fact_correction_reanalyzes_and_requires_new_review(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    old_case = db.get(Case, case_id)
    old_decision, old_action = old_case.current_decision_id, old_case.current_action_id
    response = client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Structured synthetic correction",
        "reason_code": "FACT_CORRECTION_REQUIRED",
        "fact_updates": [{"key": "electricity.billing.billed_amount", "value": 130}],
    })
    assert response.status_code == 200, response.text
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.current_decision_id != old_decision and case.current_action_id != old_action
    assert db.get(Action, old_action).status == "SUPERSEDED"
    assert not release_approved(db, case)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code in {403, 409}
    new_review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assert new_review is not None and new_review.id != review.id
    assert client.get(f"/api/cases/{case_id}").json()["decisions"] == []


def test_valid_review_is_version_bound_and_revocation_blocks_old_approval(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 200
    case = db.get(Case, case_id)
    assert release_approved(db, case)
    assert client.put(f"/api/admin/reviewers/{reviewer.id}/technical-scope", json={"families": []}).status_code == 200
    assert not release_approved(db, case)
    assert client.put(f"/api/admin/reviewers/{reviewer.id}/technical-scope", json={"families": ["E02-A"]}).status_code == 200
    assert not release_approved(db, case)  # A new authorization cannot resurrect an old approval.


def test_prepared_draft_needs_its_own_review_before_handoff(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 200
    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200 and prepared.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert "text" not in str(prepared.json()) and "amount" not in str(prepared.json())
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    assert client.post(f"/api/cases/{case_id}/submission", json={"submitted_on": "2026-09-01"}).status_code == 409
    draft_review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assert draft_review is not None and draft_review.id != review.id
    assign(client, draft_review, reviewer)
    assert client.post(f"/api/admin/reviews/{draft_review.id}/approve-release", json=APPROVAL).status_code == 200
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    first_package = client.post(f"/api/cases/{case_id}/prepare-claim")
    second_package = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert first_package.status_code == second_package.status_code == 409
    assert release_approved(db, db.get(Case, case_id))


def test_private_participant_outputs_stay_neutral_before_review(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db, "C01")
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["decisions"] == detail["actions"] == detail["deadlines"] == []
    assert detail["human_reviews"] == detail["evidence"] == []
    assert detail["current_decision_id"] is None and detail["current_action_id"] is None
    assert client.get(f"/api/cases/{case_id}/reviews").json() == []
    exported = client.get("/api/auth/export")
    assert exported.status_code == 200
    private_export = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    assert private_export["decisions"] == private_export["actions"] == []
    assert private_export["human_reviews"] == private_export["deadlines"] == []
    assert private_export["calculations"] == private_export["rule_evaluations"] == []
    assert "probability" not in str(detail).lower() and "success_score" not in str(detail).lower()
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 409
    assert client.post(f"/api/admin/reviews/{review.id}/complete", json={
        "reviewer_decision": "rubber stamp",
    }).status_code == 409
    assert len(FAMILY_MANIFEST) == 26 and gate.real_beta_gate_open() is False


def _login_backoffice(client, login_id, password):
    assert client.post("/api/backoffice-auth/logout").status_code == 200
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": login_id, "password": password,
    }).status_code == 200


def _participant_review_metadata_absent(client, case_id, reviewer_ids, private_note):
    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["decisions"] and detail.json()["actions"] == []
    assert detail.json()["current_action_id"] is None
    assert detail.json()["human_reviews"] == []
    reviews = client.get(f"/api/cases/{case_id}/reviews")
    assert reviews.status_code == 200 and reviews.json() == []
    exported = client.get("/api/auth/export")
    assert exported.status_code == 200
    private_export = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    assert private_export["decisions"] and private_export["actions"]
    assert private_export["human_reviews"] == private_export["audit_events"] == []
    for response in (detail.json(), reviews.json(), private_export,
                     client.get(f"/api/cases/{case_id}/timeline").json(),
                     client.get(f"/api/cases/{case_id}/quality").json()):
        rendered = str(response)
        for forbidden in (*reviewer_ids, private_note, "assigned_reviewer_id", "reviewer_decision",
                          "reason_code", "checklist", "authorization_id"):
            assert forbidden not in rendered


def test_completed_assignment_does_not_grant_historical_case_read(client, db, future_test_gate):
    case_id, operator, review = ready(client, db)
    first = client.post("/api/admin/reviewers", json={
        "login_id": "reviewer-a", "role": "reviewer", "initial_password": "synthetic-reviewer-a",
    }).json()["id"]
    second = client.post("/api/admin/reviewers", json={
        "login_id": "reviewer-b", "role": "reviewer", "initial_password": "synthetic-reviewer-b",
    }).json()["id"]
    for reviewer_id in (first, second):
        assert client.put(f"/api/admin/reviewers/{reviewer_id}/technical-scope", json={
            "families": ["E02-A"],
        }).status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/assign", json={"reviewer_id": first}).status_code == 200
    _login_backoffice(client, "reviewer-a", "synthetic-reviewer-a")
    assert client.get(f"/api/admin/cases/{case_id}").status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Synthetic fact correction", "reason_code": "FACT_CORRECTION_REQUIRED",
        "fact_updates": [{"key": "electricity.billing.billed_amount", "value": 130}],
    }).status_code == 200
    assert client.get(f"/api/admin/cases/{case_id}").status_code == 403
    assert client.get(f"/api/admin/cases/{case_id}/handoff").status_code == 403
    new_review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    _login_backoffice(client, "testoperator", "synthetic-operator-password")
    assert client.post(f"/api/admin/reviews/{new_review.id}/assign", json={"reviewer_id": second}).status_code == 200
    _login_backoffice(client, "reviewer-a", "synthetic-reviewer-a")
    assert client.get(f"/api/admin/cases/{case_id}").status_code == 403
    _login_backoffice(client, "reviewer-b", "synthetic-reviewer-b")
    assert client.get(f"/api/admin/cases/{case_id}").status_code == 200


def test_revoked_family_scope_immediately_removes_all_private_reads(client, db, future_test_gate):
    case_id, operator, review = ready(client, db)
    created = client.post("/api/admin/reviewers", json={
        "login_id": "scoped-reviewer", "role": "reviewer",
        "initial_password": "synthetic-scoped-password",
    })
    assert created.status_code == 201
    reviewer_id = created.json()["id"]
    scope_url = f"/api/admin/reviewers/{reviewer_id}/technical-scope"
    assert client.put(scope_url, json={"families": ["E02-A"]}).status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/assign", json={
        "reviewer_id": reviewer_id,
    }).status_code == 200
    with TestClient(app) as reviewer_client:
        assert reviewer_client.post("/api/backoffice-auth/login", json={
            "login_id": "scoped-reviewer", "password": "synthetic-scoped-password",
        }).status_code == 200
        case_url = f"/api/admin/cases/{case_id}"
        handoff_url = f"{case_url}/handoff"
        context_url = f"/api/admin/reviews/{review.id}/context"
        queue_url = "/api/admin/reviews"
        assert reviewer_client.get(case_url).status_code == 200
        assert reviewer_client.get(handoff_url).status_code == 200
        assert reviewer_client.get(context_url).status_code == 200
        assert review.id in {row["id"] for row in reviewer_client.get(queue_url).json()}

        assert client.put(scope_url, json={"families": []}).status_code == 200
        db.expire_all()
        assert db.get(HumanReview, review.id).status == "OPEN"
        assert db.get(HumanReview, review.id).assigned_reviewer_id == reviewer_id
        assert reviewer_client.get(case_url).status_code == 403
        assert reviewer_client.get(handoff_url).status_code == 403
        assert reviewer_client.get(context_url).status_code == 403
        assert review.id not in {row["id"] for row in reviewer_client.get(queue_url).json()}
        assert reviewer_client.post(f"/api/admin/reviews/{review.id}/approve-release",
                                    json=APPROVAL).status_code == 403
        assert reviewer_client.post(f"/api/admin/reviews/{review.id}/resolve-private", json={
            "outcome": "BLOCK_ACTION", "reason_code": "ACTION_BLOCKED",
        }).status_code == 403
        assert client.put(scope_url, json={"families": ["E02-A"]}).status_code == 200
        assert reviewer_client.get(case_url).status_code == 200
        assert not release_approved(db, db.get(Case, case_id))


@pytest.mark.parametrize("note", [None, "Synthetic evidence note for one fact"])
def test_private_fact_correction_needs_no_general_narrative(client, db, future_test_gate, note):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    url = f"/api/admin/reviews/{review.id}/resolve-structured"
    fact_update = {"key": "electricity.billing.billed_amount", "value": 130}
    if note is not None:
        fact_update["note"] = note
    payload = {"reason_code": "FACT_CORRECTION_REQUIRED", "fact_updates": [fact_update]}
    assert client.post(url, json={"fact_updates": [fact_update]}).status_code in {409, 422}
    assert client.post(url, json={"reason_code": "FACT_CORRECTION_REQUIRED"}).status_code == 422
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    db.expire_all()
    stored = db.get(HumanReview, review.id)
    assert stored.status == "COMPLETED"
    assert stored.reviewer_decision == "CORRECT_STRUCTURED_FACTS"
    assert stored.context_json["reason_code"] == "FACT_CORRECTION_REQUIRED"
    events = db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id)).all()
    assert all("reviewer_decision" not in str(event.payload_json) for event in events)
    if note:
        assert all(note not in str(event.payload_json) for event in events)
    evidence = db.scalar(select(Evidence).where(
        Evidence.case_id == case_id, Evidence.source_type == "human",
    ))
    assert evidence is not None and evidence.excerpt == note


def test_reanalysis_context_uses_exact_artifact_ids_and_never_old_rows(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    first = client.get(f"/api/admin/reviews/{review.id}/context").json()
    first_eval_ids = {row["id"] for row in first["rule_evaluations"]}
    first_calc_id = first["calculation"]["id"]
    assert first_eval_ids and first_calc_id
    assert db.get(Calculation, first_calc_id).case_id == case_id
    assert all(db.get(RuleEvaluation, item).case_id == case_id for item in first_eval_ids)
    assert client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Synthetic correction to amount", "reason_code": "FACT_CORRECTION_REQUIRED",
        "fact_updates": [{"key": "electricity.billing.billed_amount", "value": 130}],
    }).status_code == 200
    current = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assign(client, current, reviewer)
    second = client.get(f"/api/admin/reviews/{current.id}/context").json()
    assert second["decision"]["id"] != first["decision"]["id"]
    assert second["action"]["id"] != first["action"]["id"]
    assert second["calculation"]["id"] != first_calc_id
    assert second["calculation"]["inputs"] != first["calculation"]["inputs"]
    assert {row["id"] for row in second["rule_evaluations"]}.isdisjoint(first_eval_ids)
    refs = db.get(Decision, second["decision"]["id"]).rule_evaluations_json
    assert {row["rule_evaluation_id"] for row in refs} == {row["id"] for row in second["rule_evaluations"]}
    assert {row["calculation_id"] for row in refs} == {second["calculation"]["id"]}


def test_approved_private_diagnosis_never_releases_internal_review_metadata(client, db, future_test_gate):
    case_id, reviewer, review = ready(client, db)
    assign(client, review, reviewer)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release", json=APPROVAL).status_code == 200
    _participant_review_metadata_absent(client, case_id, (reviewer.id,), "Synthetic internal note")
    # A later structured correction invalidates the old approval, then a new
    # diagnosis can be approved without publishing the correction note.
    from app.services_v2 import upsert_fact
    case = db.get(Case, case_id)
    upsert_fact(db, case, "electricity.billing.billed_amount", 130,
                state="confirmed", user_confirmed=True, created_by="user")
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    new_review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assign(client, new_review, reviewer)
    correction = client.post(f"/api/admin/reviews/{new_review.id}/resolve-structured", json={
        "reviewer_decision": "Synthetic internal note", "reason_code": "FACT_CORRECTION_REQUIRED",
        "fact_updates": [{"key": "electricity.billing.billed_amount", "value": 140}],
    })
    assert correction.status_code == 200, correction.text
    final_review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    assign(client, final_review, reviewer)
    assert client.post(f"/api/admin/reviews/{final_review.id}/approve-release", json=APPROVAL).status_code == 200
    _participant_review_metadata_absent(client, case_id, (reviewer.id,), "Synthetic internal note")
