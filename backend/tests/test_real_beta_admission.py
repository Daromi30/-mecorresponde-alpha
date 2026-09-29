"""Closed-by-default admission and isolation regression tests (synthetic data only)."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.auth_models import RealBetaInvitation, Reviewer, User
from app.backoffice_auth import create_reviewer
from app.config import settings
from app.db import Base
from app.models import AuditEvent, Case
from app.reviews import HumanReview
from app import real_beta_gate as gate


ADMIN = {"X-Admin-Token": "test-admin-token"}
ELECTRICITY = "La factura de luz es incorrecta y me han cobrado de más"


def _register(client, email):
    response = client.post("/api/auth/register", json={
        "email": email, "password": "strong-password-for-real-beta-tests",
    })
    assert response.status_code == 201, response.text


def _invite(client, db):
    if db.query(Reviewer).count() == 0:
        create_reviewer(db, "testoperator", "synthetic-operator-password", "operator")
        db.commit()
    logged_in = client.post("/api/backoffice-auth/login", json={
        "login_id": "testoperator", "password": "synthetic-operator-password",
    })
    assert logged_in.status_code == 200, logged_in.text
    response = client.post("/api/admin/real-beta/invitations", json={"expires_in_hours": 24})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def simulated_gate(monkeypatch):
    # Simulate a future reviewed environment; the production interlock stays off.
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)


def test_gate_is_default_off_and_invalid_allowlist_fails_closed(client, monkeypatch):
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    assert gate.technical_prerequisites_ready() is False
    assert gate.real_beta_gate_open() is False
    for value in ("", "1", "yes", "enabled", "false"):
        monkeypatch.setattr(settings, "real_beta_enabled", value)
        assert not gate.real_beta_requested()
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    for value in ("", "E02-A,NOT_A_FAMILY", "E02-A,", " E02-A , "):
        monkeypatch.setattr(settings, "real_beta_allowlist", value)
        assert not gate.allowed_families()
        assert not gate.real_beta_gate_open()

    synthetic = client.post("/api/cases", json={"message": ELECTRICITY})
    assert synthetic.status_code == 200, synthetic.text
    assert synthetic.json()["mode"] == "SYNTHETIC"
    forged = client.post("/api/cases", json={"message": ELECTRICITY, "mode": "PRIVATE_REAL_BETA"})
    assert forged.status_code == 422
    closed = client.post("/api/real-beta/cases", json={"message": ELECTRICITY})
    assert closed.status_code in (401, 403)


def test_invitation_one_time_account_binding_revocation_and_no_secret_audit(client, db, simulated_gate):
    invitation = _invite(client, db)
    stored = db.get(RealBetaInvitation, invitation["invitation_id"])
    assert stored.token_digest == hashlib.sha256(invitation["token"].encode()).hexdigest()
    assert invitation["token"] not in str(stored.__dict__)

    _register(client, "first-real-beta@example.com")
    accepted = client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]})
    assert accepted.status_code == 200, accepted.text
    db.expire_all()
    assert stored.accepted_by_user_id == db.scalar(select(User).where(User.email == "first-real-beta@example.com")).id
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 404
    assert len(db.scalars(select(AuditEvent).where(AuditEvent.event_type == "REAL_BETA_INVITE_ACCEPTED")).all()) == 1
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "REAL_BETA_INVITE_ACCEPTED")) is not None
    assert all(invitation["token"] not in str(event.payload_json) for event in db.scalars(select(AuditEvent)).all())

    created = client.post("/api/real-beta/cases", json={"message": ELECTRICITY})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert created.json()["mode"] == "PRIVATE_REAL_BETA"
    assert invitation["token"] not in created.text
    assert invitation["token"] not in client.get(f"/api/cases/{case_id}").text
    assert db.get(Case, case_id).user_id == stored.accepted_by_user_id

    client.post("/api/auth/logout")
    _register(client, "second-real-beta@example.com")
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 404
    assert client.get(f"/api/cases/{case_id}").status_code in (403, 404)
    assert client.post("/api/real-beta/cases", json={"message": ELECTRICITY}).status_code == 403

    assert client.post(f"/api/admin/real-beta/invitations/{invitation['invitation_id']}/revoke").status_code == 200
    assert client.post(f"/api/admin/real-beta/invitations/{invitation['invitation_id']}/revoke").status_code == 200
    assert len(db.scalars(select(AuditEvent).where(AuditEvent.event_type == "REAL_BETA_INVITE_REVOKED")).all()) == 1
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={
        "email": "first-real-beta@example.com", "password": "strong-password-for-real-beta-tests",
    }).status_code == 200
    assert client.post("/api/real-beta/cases", json={"message": ELECTRICITY}).status_code == 403
    assert client.get(f"/api/cases/{case_id}").status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 403


def test_expired_invite_and_family_rejection_do_not_persist_intake(client, db, simulated_gate):
    invitation = _invite(client, db)
    _register(client, "expiry-real-beta@example.com")
    stored = db.get(RealBetaInvitation, invitation["invitation_id"])
    stored.expires_at = gate.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 404
    assert stored.status == "ISSUED"

    another = _invite(client, db)
    assert client.post("/api/real-beta/invitations/accept", json={"token": another["token"]}).status_code == 200
    before = db.query(Case).count()
    rejected = client.post("/api/real-beta/cases", json={"message": "Compré un televisor defectuoso y no me respetan la garantía"})
    assert rejected.status_code == 403, rejected.text
    assert db.query(Case).count() == before
    blocked = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "REAL_BETA_FAMILY_BLOCKED")).all()
    assert blocked
    assert all("televisor" not in str(item.payload_json) for item in blocked)


def test_revoked_unaccepted_and_unknown_invites_share_non_enumerating_response(client, db, simulated_gate):
    invitation = _invite(client, db)
    _register(client, "invalid-real-beta@example.com")
    assert client.post(f"/api/admin/real-beta/invitations/{invitation['invitation_id']}/revoke").status_code == 200
    revoked = client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]})
    unknown = client.post("/api/real-beta/invitations/accept", json={"token": "not-an-invitation-" + "x" * 40})
    assert revoked.status_code == unknown.status_code == 404
    assert revoked.json() == unknown.json()


def test_real_case_mutation_blocks_when_gate_closes_but_owner_can_read(client, db, simulated_gate, monkeypatch):
    invitation = _invite(client, db)
    _register(client, "closure-real-beta@example.com")
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 200
    case_id = client.post("/api/real-beta/cases", json={"message": ELECTRICITY}).json()["id"]
    review = HumanReview(case_id=case_id, reason="TEST_REVIEW", status="OPEN")
    db.add(review)
    db.commit()
    monkeypatch.setattr(settings, "real_beta_enabled", "false")
    assert client.get(f"/api/cases/{case_id}").status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 403
    assert client.post(f"/api/admin/reviews/{review.id}/assign", json={"assigned_to": "synthetic-reviewer"}).status_code == 403
    assert db.get(HumanReview, review.id).assigned_to is None


def test_admin_invitation_requires_admin_secret(client):
    assert client.post("/api/admin/real-beta/invitations", json={"expires_in_hours": 24}).status_code == 401
    assert client.post("/api/admin/real-beta/invitations", json={"expires_in_hours": 24}, headers=ADMIN).status_code == 403


def test_direct_private_api_requires_login_even_when_gate_is_simulated_open(client, simulated_gate):
    assert client.post("/api/real-beta/cases", json={"message": ELECTRICITY}).status_code == 401
    assert client.post("/api/real-beta/invitations/accept", json={"token": "x" * 43}).status_code == 401


def test_admission_expires_at_exact_boundary_and_does_not_delete_case(client, db, simulated_gate):
    invitation = _invite(client, db)
    _register(client, "boundary-real-beta@example.com")
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 200
    user = db.scalar(select(User).where(User.email == "boundary-real-beta@example.com"))
    item = db.get(RealBetaInvitation, invitation["invitation_id"])
    deadline = gate.utcnow() + timedelta(minutes=5)
    item.expires_at = deadline
    db.commit()
    assert gate.admission_active(db, user.id, deadline - timedelta(microseconds=1))
    assert not gate.admission_active(db, user.id, deadline)
    assert not gate.admission_active(db, user.id, deadline + timedelta(microseconds=1))
    item.expires_at = gate.utcnow() + timedelta(hours=1)
    db.commit()
    created = client.post("/api/real-beta/cases", json={"message": ELECTRICITY})
    assert created.status_code == 201, created.text
    item.expires_at = gate.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/real-beta/cases", json={"message": ELECTRICITY}).status_code == 403
    assert client.post(f"/api/cases/{created.json()['id']}/diagnose").status_code == 403
    assert client.get(f"/api/cases/{created.json()['id']}").status_code == 200
    assert db.get(Case, created.json()["id"]) is not None


def test_reclassification_outside_allowlist_stops_without_material_decision(client, db, simulated_gate, monkeypatch):
    monkeypatch.setattr(settings, "real_beta_allowlist", "E06")
    invitation = _invite(client, db)
    _register(client, "reclass-real-beta@example.com")
    assert client.post("/api/real-beta/invitations/accept", json={"token": invitation["token"]}).status_code == 200
    created = client.post("/api/real-beta/cases", json={
        "message": "Mi factura de luz tiene una lectura estimada porque falló la lectura remota",
    })
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    for key, value in (
        ("electricity.reading_issue_invoice_date", "2026-09-01"),
        ("electricity.meter_fraud_tampering_or_complex_technical_issue", False),
        ("electricity.reading_issue_type", "overbilling_regularization"),
    ):
        response = client.post(f"/api/cases/{case_id}/facts", json={
            "key": key, "value": value, "state": "confirmed", "user_confirmed": True,
        })
        assert response.status_code == 200, response.text
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["status"] == "HUMAN_REVIEW"
    assert diagnosis.json()["decision_id"] is None
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.family == "E06"
    assert case.status == "HUMAN_REVIEW"
    assert case.current_decision_id is None
    assert db.scalar(select(AuditEvent).where(
        AuditEvent.case_id == case_id, AuditEvent.event_type == "REAL_BETA_FAMILY_BLOCKED",
    )) is not None
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code in (403, 409)


def test_conditional_acceptance_cannot_bind_two_accounts_concurrently(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'invite-race.sqlite'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    expiry = gate.utcnow() + timedelta(hours=1)
    with Session(engine) as session:
        first = User(email="race-one@example.com", password_hash="synthetic")
        second = User(email="race-two@example.com", password_hash="synthetic")
        invitation = RealBetaInvitation(token_digest="a" * 64, status="ISSUED", expires_at=expiry)
        session.add_all((first, second, invitation))
        session.commit()
        ids = (first.id, second.id)
        invitation_id = invitation.id
    barrier = Barrier(2)

    def attempt(user_id):
        barrier.wait(timeout=10)
        with Session(engine) as session:
            result = session.execute(
                update(RealBetaInvitation)
                .where(
                    RealBetaInvitation.id == invitation_id,
                    RealBetaInvitation.status == "ISSUED",
                    RealBetaInvitation.revoked_at.is_(None),
                    RealBetaInvitation.expires_at > gate.utcnow(),
                )
                .values(status="ACCEPTED", accepted_by_user_id=user_id, accepted_at=gate.utcnow())
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return result.rowcount

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ids)) == [0, 1]
    with Session(engine) as session:
        assert session.get(RealBetaInvitation, invitation_id).accepted_by_user_id in ids
    engine.dispose()
