"""RB-022 opening governance, using only synthetic identities and fixtures."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import real_beta_gate as gate
from app.auth_models import RealBetaInvitation, RealBetaRelease, ReleaseApproval, User
from app.config import settings
from app.models import Case
from app.private_beta_release import release_approved
from app.services_v2 import upsert_fact
from release_test_support import eligible_test_release


@pytest.fixture
def synthetic_prerequisites(monkeypatch):
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)


def _user(db, index=1):
    user = User(email=f"rb022-{index}@example.com", password_hash="synthetic")
    db.add(user)
    db.flush()
    return user


def test_missing_invalid_and_inconsistent_configuration_stays_closed(db, monkeypatch):
    assert not gate.real_beta_gate_open(db)
    user = _user(db)
    release, _, _ = eligible_test_release(db, [user])
    for flag, allowlist in (("false", "E02-A,C01"), ("", "E02-A,C01"),
                            ("true", ""), ("true", "all"), ("true", "E02-A"),
                            ("true", "E02-A,C01,E06"), ("true", "E02-A,E02-A")):
        monkeypatch.setattr(settings, "real_beta_enabled", flag)
        monkeypatch.setattr(settings, "real_beta_allowlist", allowlist)
        assert not gate.real_beta_gate_open(db)
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)
    assert gate.real_beta_gate_open(db)
    release.status = "CLOSED"
    db.commit()
    assert not gate.real_beta_gate_open(db)


def test_approvals_scope_authority_window_and_rollback_fail_closed(db, synthetic_prerequisites):
    user = _user(db)
    release, owner, professional = eligible_test_release(db, [user])
    assert gate.real_beta_gate_open(db)
    assert gate.eligible_release(db, release.ends_at + timedelta(seconds=1)) is None
    approvals = db.scalars(select(ReleaseApproval).where(ReleaseApproval.release_id == release.id)).all()
    professional_approval = next(row for row in approvals if row.authority_type == "PROFESSIONAL_APPROVER")
    db.delete(professional_approval)
    db.commit()
    assert not gate.real_beta_gate_open(db)
    professional_approval = ReleaseApproval(
        release_id=release.id, release_version=release.version,
        scope_fingerprint=release.scope_fingerprint, authority_id=professional.id,
        authority_type="PROFESSIONAL_APPROVER",
    )
    db.add(professional_approval)
    db.commit()
    assert gate.real_beta_gate_open(db)
    professional_approval.release_version += 1
    db.commit()
    assert not gate.real_beta_gate_open(db)
    professional_approval.release_version = release.version
    professional_approval.scope_fingerprint = "f" * 64
    db.commit()
    assert not gate.real_beta_gate_open(db)
    professional_approval.scope_fingerprint = release.scope_fingerprint
    db.commit()
    assert gate.real_beta_gate_open(db)
    release.cohort_user_ids_json = [str(user.id), str(_user(db, 2).id)]
    db.commit()
    assert not gate.real_beta_gate_open(db)
    release.cohort_user_ids_json = [user.id]
    db.commit()
    professional.revoked_at = gate.utcnow()
    db.commit()
    assert not gate.real_beta_gate_open(db)
    professional.revoked_at = None
    release.ends_at = gate.utcnow() - timedelta(seconds=1)
    db.commit()
    assert not gate.real_beta_gate_open(db)
    release.status = "REVOKED"
    db.commit()
    assert not gate.real_beta_gate_open(db)
    assert owner.authority_type == "OWNER_APPROVER"


@pytest.mark.parametrize("invalid_approval", [
    "owner_only", "professional_only", "same_type", "same_identity", "other_release",
])
def test_approval_roles_and_release_must_be_independent_and_identical_scope(
    db, synthetic_prerequisites, invalid_approval,
):
    user = _user(db)
    release, owner, professional = eligible_test_release(db, [user])
    approvals = db.scalars(select(ReleaseApproval).where(ReleaseApproval.release_id == release.id)).all()
    owner_row = next(row for row in approvals if row.authority_type == "OWNER_APPROVER")
    professional_row = next(row for row in approvals if row.authority_type == "PROFESSIONAL_APPROVER")
    if invalid_approval == "owner_only":
        db.delete(professional_row)
    elif invalid_approval == "professional_only":
        db.delete(owner_row)
    elif invalid_approval == "same_type":
        professional_row.authority_type = "OWNER_APPROVER"
    elif invalid_approval == "same_identity":
        professional_row.authority_id = owner.id
    else:
        other = RealBetaRelease(
            version=1, status="DRAFT", families_json=["E02-A", "C01"],
            cohort_user_ids_json=[user.id], max_users=10, max_cases_total=10,
            max_active_cases_per_user=1, max_daily_admissions=2,
            max_duration_days=14, starts_at=release.starts_at,
            ends_at=release.ends_at, scope_fingerprint="0" * 64,
        )
        db.add(other)
        db.flush()
        professional_row.release_id = other.id
    if invalid_approval == "same_identity":
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        return
    db.commit()
    assert not gate.real_beta_gate_open(db)
    assert professional.authority_type == "PROFESSIONAL_APPROVER"


def test_cohort_size_and_fallback_family_are_exact(db, synthetic_prerequisites, monkeypatch):
    users = [_user(db, index) for index in range(11)]
    release, _, _ = eligible_test_release(db, users)
    assert not gate.real_beta_gate_open(db)
    release.cohort_user_ids_json = [users[0].id]
    db.commit()
    assert not gate.real_beta_gate_open(db)  # A changed cohort invalidates its approvals.
    release.status = "CLOSED"
    db.commit()
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A")
    fallback, _, _ = eligible_test_release(db, [users[0]], families=("E02-A",))
    assert gate.real_beta_gate_open(db)
    assert fallback.max_users == 5 and fallback.max_cases_total == 5
    assert "C01" not in fallback.families_json


def test_operator_routes_cannot_grant_release_authority(client, db):
    from app.backoffice_auth import create_reviewer
    create_reviewer(db, "synthetic-operator", "synthetic-operator-password", "operator")
    db.commit()
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": "synthetic-operator", "password": "synthetic-operator-password",
    }).status_code == 200
    for path in ("/api/admin/real-beta/authorities", "/api/admin/real-beta/releases",
                 "/api/admin/reviewers/release-authority"):
        assert client.post(path, json={"authority_type": "PROFESSIONAL_APPROVER"}).status_code in {404, 405}


def test_membership_and_release_output_rollback(db, synthetic_prerequisites):
    member, outsider = _user(db), _user(db, 2)
    release, _, _ = eligible_test_release(db, [member])
    invite = RealBetaInvitation(
        release_id=release.id, intended_user_id=member.id,
        accepted_by_user_id=member.id, status="ACCEPTED",
        token_digest="a" * 64, accepted_at=gate.utcnow(),
        expires_at=gate.utcnow() + timedelta(hours=1),
    )
    db.add(invite)
    db.commit()
    assert gate.admission_active(db, member.id)
    assert not gate.admission_active(db, outsider.id)
    invite.revoked_at = gate.utcnow()
    db.commit()
    assert not gate.admission_active(db, member.id)
    invite.revoked_at = None
    db.commit()
    assert gate.admission_active(db, member.id)
    case = Case(mode=gate.REAL_MODE, user_id=member.id,
                real_beta_release_id=release.id, family="E02-A")
    db.add(case)
    db.commit()
    # Even an otherwise approved actionable result cannot survive closure.
    release.status = "CLOSED"
    db.commit()
    assert not gate.admission_active(db, member.id)
    assert not release_approved(db, case)
    with pytest.raises(HTTPException) as denied:
        upsert_fact(db, case, "electricity.billing.billing_period", "2026-09")
    assert denied.value.status_code == 403


def test_release_close_remains_closed_after_new_database_session(db, synthetic_prerequisites):
    user = _user(db)
    release, _, _ = eligible_test_release(db, [user])
    with Session(db.bind) as restarted_session:
        assert gate.real_beta_gate_open(restarted_session)
    release.status = "CLOSED"
    db.commit()
    with Session(db.bind) as restarted_session:
        assert not gate.real_beta_gate_open(restarted_session)


def test_evaluation_exception_is_closed(db, synthetic_prerequisites, monkeypatch):
    user = _user(db)
    eligible_test_release(db, [user])
    monkeypatch.setattr(gate, "_approved", lambda *_: 1 / 0)
    assert not gate.real_beta_gate_open(db)
