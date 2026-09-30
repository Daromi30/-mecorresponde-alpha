"""Synthetic-only tests for individual backoffice authorization and attribution."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import real_beta_gate as gate
from app.auth_models import RealBetaInvitation, Reviewer, ReviewerSession, User
from app.auth_throttle import AuthThrottleState
from app.backoffice_auth import COOKIE, create_reviewer, login_throttle
from app.config import settings
from app.models import AuditEvent, Case
from app.main import app
from app.admin_auth import require_admin
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review


ADMIN = {"X-Admin-Token": "test-admin-token"}
PASSWORD = "synthetic-reviewer-password"


def seed(db, login_id, role="reviewer"):
    reviewer = create_reviewer(db, login_id, PASSWORD, role)
    db.commit()
    return reviewer


def login(client, login_id, password=PASSWORD):
    client.cookies.clear()
    response = client.post("/api/backoffice-auth/login", json={
        "login_id": login_id, "password": password,
    })
    assert response.status_code == 200, response.text
    return client.cookies.get(COOKIE)


def use_cookie(client, token):
    client.cookies.clear()
    client.cookies.set(COOKIE, token, path="/api")


def private_review(db, owner_email="private-owner@example.com", token_digest="b" * 64):
    owner = User(email=owner_email, password_hash="synthetic")
    db.add(owner)
    db.flush()
    invitation = RealBetaInvitation(
        token_digest=token_digest, status="ACCEPTED", accepted_by_user_id=owner.id,
        accepted_at=gate.utcnow(), expires_at=gate.utcnow() + timedelta(hours=2),
    )
    db.add(invitation)
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    case.mode = gate.REAL_MODE
    case.user_id = owner.id
    review = create_human_review(db, case, reason="MATERIAL_FACT_REVIEW", priority="HIGH")
    db.commit()
    return case, review


@pytest.fixture
def simulated_gate(monkeypatch):
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)


def test_two_reviewers_have_distinct_server_actors_and_cannot_spoof_assignment(client, db, simulated_gate):
    operator = seed(db, "operator", "operator")
    reviewer_a = seed(db, "reviewera")
    reviewer_b = seed(db, "reviewerb")
    case, review = private_review(db)

    op_cookie = login(client, "operator")
    assert client.get("/api/admin/reviews").status_code == 200
    assert client.get(f"/api/admin/cases/{case.id}").status_code == 200
    assert client.get(f"/api/admin/cases/{case.id}/handoff").status_code == 200
    assigned = client.post(f"/api/admin/reviews/{review.id}/assign", json={"reviewer_id": reviewer_a.id})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned_reviewer_id"] == reviewer_a.id

    a_cookie = login(client, "reviewera")
    assert client.get(f"/api/admin/cases/{case.id}").status_code == 200
    spoof = client.post(f"/api/admin/reviews/{review.id}/assign", json={"assigned_to": "reviewerb"})
    assert spoof.status_code == 403
    b_cookie = login(client, "reviewerb")
    denied = client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Intento sintético de revisión ajena.",
        "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80.0}],
    })
    assert denied.status_code == 403
    use_cookie(client, a_cookie)
    structured = client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Importes sintéticos contrastados.",
        "fact_updates": [
            {"key": "electricity.billing.invoice_date", "value": "2026-07-01"},
            {"key": "electricity.billing.billed_amount", "value": 120.0},
            {"key": "electricity.billing.correct_amount", "value": 80.0},
        ],
    })
    assert structured.status_code == 200, structured.text

    use_cookie(client, b_cookie)
    assert client.get(f"/api/admin/cases/{case.id}").status_code == 200
    assert client.get(f"/api/admin/cases/{case.id}/handoff").status_code == 200
    db.expire_all()
    reads = db.scalars(select(AuditEvent).where(
        AuditEvent.case_id == case.id, AuditEvent.event_type == "BACKOFFICE_CASE_READ",
    )).all()
    assert {event.actor_reviewer_id for event in reads} == {operator.id, reviewer_a.id, reviewer_b.id}
    assignment = db.scalar(select(AuditEvent).where(
        AuditEvent.case_id == case.id, AuditEvent.event_type == "HUMAN_REVIEW_ASSIGNED",
    ))
    resolution = db.scalar(select(AuditEvent).where(
        AuditEvent.case_id == case.id, AuditEvent.event_type == "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
    ))
    assert assignment.actor_reviewer_id == operator.id
    assert assignment.payload_json["assigned_reviewer_id"] == reviewer_a.id
    assert resolution.actor_reviewer_id == reviewer_a.id
    assert db.get(HumanReview, review.id).assigned_reviewer_id == reviewer_a.id
    assert op_cookie != a_cookie != b_cookie


def test_shared_token_and_claimant_cookie_cannot_read_private_case_or_mutate_review(client, db):
    case, review = private_review(db)
    queue = client.get("/api/admin/reviews", headers=ADMIN)
    assert queue.status_code == 200
    assert all(item["case_id"] != case.id for item in queue.json())
    assert client.get("/api/admin/stats", headers=ADMIN).json()["total_cases"] == 0
    for path in (f"/api/admin/cases/{case.id}", f"/api/admin/cases/{case.id}/handoff"):
        assert client.get(path, headers=ADMIN).status_code == 404
    for suffix, payload in (
        ("assign", {"reviewer_id": "synthetic"}),
        ("complete", {"reviewer_decision": "synthetic"}),
        ("reclassify", {"target_family": "C01", "reviewer_decision": "synthetic"}),
        ("escalate-professional", {"reviewer_decision": "synthetic"}),
        ("resolve-structured", {"reviewer_decision": "synthetic", "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80}]}),
    ):
        assert client.post(f"/api/admin/reviews/{review.id}/{suffix}", json=payload, headers=ADMIN).status_code == 404
    client.historical_account("claimant-only@example.com", "synthetic-claimant-password")
    assert client.get(f"/api/admin/cases/{case.id}").status_code == 401
    assert client.get("/api/admin/reviews").status_code == 401
    db.expire_all()
    assert db.get(HumanReview, review.id).status == "OPEN"


def test_private_reclassification_and_professional_escalation_use_session_actor(client, db, simulated_gate):
    operator = seed(db, "operator", "operator")
    reviewer = seed(db, "reviewera")
    routing_case, routing_review = private_review(db)
    routing_case.family = None
    routing_case.status = "HUMAN_REVIEW"
    routing_review.reason = "UNSUPPORTED_CLASSIFICATION"
    escalation_case, escalation_review = private_review(
        db, "second-private-owner@example.com", "c" * 64,
    )
    escalation_case.status = "HUMAN_REVIEW"
    escalation_review.reason = "POST_DENIAL_ESCALATION_REVIEW"
    db.commit()

    login(client, "operator")
    # An unclassified private case is ineligible under the admission gate: even an
    # operator cannot assign or reclassify it through this administrative route.
    denied = client.post(f"/api/admin/reviews/{routing_review.id}/reclassify", json={
        "target_family": "E02-A", "reviewer_decision": "Clasificación ficticia revisada.",
    })
    assert denied.status_code == 403
    assigned = client.post(f"/api/admin/reviews/{escalation_review.id}/assign", json={"reviewer_id": reviewer.id})
    assert assigned.status_code == 200, assigned.text
    login(client, "reviewera")
    escalated = client.post(f"/api/admin/reviews/{escalation_review.id}/escalate-professional", json={
        "reviewer_decision": "Escalado ficticio para revisión profesional.",
    })
    assert escalated.status_code == 200, escalated.text

    db.expire_all()
    for case, event_type, actor_id in (
        (routing_case, "BACKOFFICE_ACCESS_DENIED", operator.id),
        (escalation_case, "PROFESSIONAL_ESCALATION_REQUIRED", reviewer.id),
    ):
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.case_id == case.id, AuditEvent.event_type == event_type,
        ))
        assert event.actor_reviewer_id == actor_id
    assignments = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "HUMAN_REVIEW_ASSIGNED")).all()
    assert len(assignments) == 1
    assert {event.actor_reviewer_id for event in assignments} == {operator.id}


def test_reviewer_session_logout_expiry_revocation_disable_and_password_rotation(client, db):
    operator = seed(db, "operator", "operator")
    reviewer = seed(db, "reviewera")
    token = login(client, "reviewera")
    assert token and token not in str(db.scalars(select(ReviewerSession)).all())
    assert client.get("/api/admin/health").status_code == 200
    assert client.post("/api/backoffice-auth/logout").status_code == 200
    use_cookie(client, token)
    assert client.get("/api/admin/health").status_code == 401

    token = login(client, "reviewera")
    session = db.scalar(select(ReviewerSession).where(ReviewerSession.reviewer_id == reviewer.id, ReviewerSession.revoked_at.is_(None)))
    session.expires_at = gate.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/admin/health").status_code == 401

    token = login(client, "reviewera")
    op_token = login(client, "operator")
    assert client.post(f"/api/admin/reviewers/{reviewer.id}/revoke-sessions").status_code == 200
    use_cookie(client, token)
    assert client.get("/api/admin/health").status_code == 401
    token = login(client, "reviewera")
    use_cookie(client, op_token)
    assert client.post(f"/api/admin/reviewers/{reviewer.id}/disable").status_code == 200
    use_cookie(client, token)
    assert client.get("/api/admin/health").status_code == 401
    db.expire_all()
    assert db.get(Reviewer, reviewer.id).disabled_at is not None

    use_cookie(client, op_token)
    changed = client.post("/api/backoffice-auth/password", json={
        "current_password": PASSWORD, "new_password": "another-synthetic-password",
    })
    assert changed.status_code == 200, changed.text
    use_cookie(client, op_token)
    assert client.get("/api/admin/health").status_code == 401
    assert client.post("/api/backoffice-auth/login", json={"login_id": "operator", "password": PASSWORD}).status_code == 401
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": "operator", "password": "another-synthetic-password",
    }).status_code == 200


def test_reviewer_cannot_provision_or_change_roles_and_login_is_non_enumerating_throttled(client, db):
    seed(db, "operator", "operator")
    reviewer = seed(db, "reviewera")
    login(client, "reviewera")
    payload = {"login_id": "thirdperson", "role": "operator", "initial_password": PASSWORD}
    assert client.post("/api/admin/reviewers", json=payload).status_code == 403
    assert client.post(f"/api/admin/reviewers/{reviewer.id}/role", json={"role": "operator"}).status_code == 403
    assert db.scalar(select(Reviewer).where(Reviewer.login_id == "thirdperson")) is None

    original_limit = login_throttle.limit
    login_throttle.limit = 2
    try:
        wrong = client.post("/api/backoffice-auth/login", json={"login_id": "operator", "password": "wrong-synthetic-password"})
        unknown = client.post("/api/backoffice-auth/login", json={"login_id": "unknown", "password": "wrong-synthetic-password"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert client.post("/api/backoffice-auth/login", json={"login_id": "operator", "password": "wrong-synthetic-password"}).status_code == 401
        assert client.post("/api/backoffice-auth/login", json={"login_id": "operator", "password": "wrong-synthetic-password"}).status_code == 429
    finally:
        login_throttle.limit = original_limit
        login_throttle.reset(db)
        db.commit()
    assert db.scalars(select(AuthThrottleState)).all() == []


def test_private_read_audit_failure_closes_response(client, db, monkeypatch):
    seed(db, "operator", "operator")
    case, _ = private_review(db)
    login(client, "operator")
    original = db.commit

    def unavailable():
        raise RuntimeError("synthetic audit persistence failure")

    monkeypatch.setattr(db, "commit", unavailable)
    with pytest.raises(RuntimeError, match="synthetic audit persistence failure"):
        client.get(f"/api/admin/cases/{case.id}")
    monkeypatch.setattr(db, "commit", original)
    db.rollback()


def test_origin_fetch_site_and_secret_free_audit(client, db, caplog):
    reviewer = seed(db, "reviewera")
    forbidden = client.post("/api/backoffice-auth/login", json={
        "login_id": "reviewera", "password": PASSWORD,
    }, headers={"Origin": "https://evil.example.com", "Sec-Fetch-Site": "cross-site"})
    assert forbidden.status_code == 403
    token = login(client, "reviewera")
    response = client.post("/api/admin/reviewers", json={
        "login_id": "intruder", "role": "operator", "initial_password": PASSWORD,
    }, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert reviewer.id
    material = str([row.payload_json for row in db.scalars(select(AuditEvent)).all()]) + caplog.text
    assert PASSWORD not in material
    assert token not in material
    assert "Authorization" not in material


def test_all_admin_routes_have_central_guard_and_cookie_attributes(client, db, monkeypatch):
    admin_paths = [
        route for included in app.routes
        for route in getattr(getattr(included, "original_router", None), "routes", [])
        if getattr(route, "path", "").startswith("/api/admin")
    ]
    assert admin_paths
    for route in admin_paths:
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies), route.path

    seed(db, "operator", "operator")
    monkeypatch.setattr(settings, "render", True)
    response = client.post("/api/backoffice-auth/login", json={"login_id": "operator", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/api" in cookie
    assert PASSWORD not in cookie


def test_last_operator_cannot_be_disabled_or_demoted(client, db):
    operator = seed(db, "operator", "operator")
    login(client, "operator")
    assert client.post(f"/api/admin/reviewers/{operator.id}/disable").status_code == 409
    assert client.post(f"/api/admin/reviewers/{operator.id}/role", json={"role": "reviewer"}).status_code == 409
    db.expire_all()
    assert db.get(Reviewer, operator.id).disabled_at is None
    assert db.get(Reviewer, operator.id).role == "operator"
