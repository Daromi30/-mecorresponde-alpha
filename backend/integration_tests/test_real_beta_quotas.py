"""Disposable PostgreSQL-only RB-022 races; all identities are fictional."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

from app import real_beta_gate as gate
from app.auth_models import RealBetaInvitation, RealBetaRelease, ReleaseApproval, ReleaseAuthority, User
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Case
from app.routers.real_beta import InvitationAccept, PrivateCaseCreate, accept_invitation, create_private_case


def _setup(users_count):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    now = gate.utcnow()
    with SessionLocal() as db:
        users = [User(email=f"rb022-race-{index}@example.com", password_hash="synthetic")
                 for index in range(users_count)]
        owner = ReleaseAuthority(authority_type="OWNER_APPROVER")
        professional = ReleaseAuthority(authority_type="PROFESSIONAL_APPROVER")
        db.add_all([*users, owner, professional])
        db.flush()
        release = RealBetaRelease(
            version=1, status="OPEN", families_json=["E02-A", "C01"],
            cohort_user_ids_json=[user.id for user in users],
            max_users=10, max_cases_total=10, max_active_cases_per_user=1,
            max_daily_admissions=2, max_duration_days=14,
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(days=1),
            scope_fingerprint="0" * 64,
        )
        db.add(release)
        db.flush()
        release.scope_fingerprint = gate.scope_fingerprint(release)
        for authority in (owner, professional):
            db.add(ReleaseApproval(
                release_id=release.id, release_version=release.version,
                scope_fingerprint=release.scope_fingerprint, authority_id=authority.id,
                authority_type=authority.authority_type,
            ))
        db.commit()
        return release.id, [user.id for user in users]


def _accepted(db, release_id, user_id, index):
    db.add(RealBetaInvitation(
        release_id=release_id, intended_user_id=user_id,
        accepted_by_user_id=user_id, status="ACCEPTED",
        token_digest=f"{index:064x}", accepted_at=gate.utcnow(),
        expires_at=gate.utcnow() + timedelta(hours=1),
    ))


def test_postgres_release_lock_serializes_case_and_daily_admission_quotas(monkeypatch):
    assert engine.dialect.name == "postgresql"
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)
    release_id, users = _setup(3)
    with SessionLocal() as db:
        for index, user_id in enumerate(users):
            _accepted(db, release_id, user_id, index + 1)
        db.commit()

    barrier = Barrier(2)

    def create(user_id):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                create_private_case(PrivateCaseCreate(family="E02-A", age_18_plus_attested=True),
                                    user=db.get(User, user_id), db=db)
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, [users[0], users[0]])) == [201, 403]
    with SessionLocal() as db:
        assert len(db.scalars(select(Case).where(Case.real_beta_release_id == release_id)).all()) == 1
        # Exactly one total-case slot remains for two different cohort members.
        for index in range(8):
            db.add(Case(mode=gate.REAL_MODE, user_id=users[0], family="E02-A",
                        real_beta_release_id=release_id, closed_at=gate.utcnow()))
        db.commit()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, users[1:])) == [201, 403]
    with SessionLocal() as db:
        assert len(db.scalars(select(Case).where(Case.real_beta_release_id == release_id)).all()) == 10

    release_id, users = _setup(3)
    tokens = [f"synthetic-race-token-{index}" + "x" * 40 for index in range(3)]
    with SessionLocal() as db:
        _accepted(db, release_id, users[0], 100)
        for index in (1, 2):
            db.add(RealBetaInvitation(
                release_id=release_id, intended_user_id=users[index], status="ISSUED",
                token_digest=hashlib.sha256(tokens[index].encode()).hexdigest(),
                expires_at=gate.utcnow() + timedelta(hours=1),
            ))
        db.commit()
    barrier = Barrier(2)

    def accept(index):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                accept_invitation(InvitationAccept(token=tokens[index]), user=db.get(User, users[index]), db=db)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept, (1, 2))) == [200, 404]
    with SessionLocal() as db:
        accepted = db.scalars(select(RealBetaInvitation).where(
            RealBetaInvitation.release_id == release_id, RealBetaInvitation.status == "ACCEPTED",
        )).all()
        assert len(accepted) == 2
