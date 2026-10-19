"""Closed-by-default, server-owned admission boundary for a future private beta.

This is deliberately not a launch approval. The public synthetic intake remains open,
so real-person data must not be accepted until its separate operational/privacy gates
and backoffice attribution are built and independently approved.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import RealBetaInvitation, RealBetaRelease, ReleaseApproval, ReleaseAuthority
from .config import settings
from .db import engine
from .family_manifest import FAMILY_MANIFEST
from .models import AuditEvent, Case
from .private_beta_release import INITIAL_FAMILIES
from .privacy_information import privacy_information_status
from .storage import StorageConfigurationError, storage_status


REAL_MODE = "PRIVATE_REAL_BETA"
SYNTHETIC_MODE = "SYNTHETIC"
AUTHORITY_TYPES = frozenset({"OWNER_APPROVER", "PROFESSIONAL_APPROVER"})
RELEASE_POLICIES = {
    frozenset({"E02-A", "C01"}): (10, 10, 1, 2, 14),
    frozenset({"E02-A"}): (5, 5, 1, 1, 7),
}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def real_beta_requested() -> bool:
    return isinstance(settings.real_beta_enabled, str) and settings.real_beta_enabled == "true"


def allowed_families() -> frozenset[str]:
    raw = settings.real_beta_allowlist
    if not isinstance(raw, str) or not raw.strip():
        return frozenset()
    values = raw.split(",")
    if (len(values) != len(set(values)) or any(
        not value or value != value.strip() or value not in FAMILY_MANIFEST or value not in INITIAL_FAMILIES
        for value in values
    )):
        return frozenset()
    return frozenset(values)


def technical_prerequisites_ready() -> bool:
    if engine.dialect.name != "postgresql" or not privacy_information_status(settings).ready:
        return False
    if not settings.transactional_email_operational:
        return False
    try:
        return storage_status().persistent
    except StorageConfigurationError:
        return False


def scope_fingerprint(release: RealBetaRelease) -> str:
    """Canonical scope; any material change makes previous approvals unusable."""
    payload = {
        "id": release.id, "version": release.version,
        "families": release.families_json, "cohort_user_ids": release.cohort_user_ids_json,
        "max_users": release.max_users, "max_cases_total": release.max_cases_total,
        "max_active_cases_per_user": release.max_active_cases_per_user,
        "max_daily_admissions": release.max_daily_admissions,
        "max_duration_days": release.max_duration_days,
        "starts_at": utc(release.starts_at).isoformat(),
        "ends_at": utc(release.ends_at).isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _valid_scope(release: RealBetaRelease, at: datetime) -> bool:
    families = release.families_json
    cohort = release.cohort_user_ids_json
    if (type(release.version) is not int or release.version < 1
            or not isinstance(families, list) or not families
            or not all(isinstance(value, str) for value in families)
            or len(set(families)) != len(families)
            or frozenset(families) != allowed_families()
            or not isinstance(cohort, list) or not cohort
            or not all(isinstance(value, str) for value in cohort)
            or len(set(cohort)) != len(cohort)):
        return False
    for value in cohort:
        if str(uuid.UUID(value)) != value:
            return False
    limits = (release.max_users, release.max_cases_total,
              release.max_active_cases_per_user, release.max_daily_admissions,
              release.max_duration_days)
    if limits != RELEASE_POLICIES.get(frozenset(families)) or len(cohort) > release.max_users:
        return False
    start, end = utc(release.starts_at), utc(release.ends_at)
    if not start <= at < end or end - start > timedelta(days=release.max_duration_days):
        return False
    return release.scope_fingerprint == scope_fingerprint(release)


def _approved(db: Session, release: RealBetaRelease, at: datetime) -> bool:
    rows = db.scalars(select(ReleaseApproval).where(ReleaseApproval.release_id == release.id)).all()
    by_type: dict[str, set[str]] = {kind: set() for kind in AUTHORITY_TYPES}
    for row in rows:
        if (row.release_version != release.version
                or row.scope_fingerprint != release.scope_fingerprint
                or row.authority_type not in AUTHORITY_TYPES
                or not utc(release.created_at) <= utc(row.approved_at) <= at):
            continue
        authority = db.get(ReleaseAuthority, row.authority_id)
        if (authority is None or authority.revoked_at is not None
                or authority.authority_type != row.authority_type
                or utc(authority.created_at) > utc(row.approved_at)):
            continue
        by_type[row.authority_type].add(authority.id)
    return any(owner != professional for owner in by_type["OWNER_APPROVER"]
               for professional in by_type["PROFESSIONAL_APPROVER"])


def eligible_release(db: Session | None, at: datetime | None = None) -> RealBetaRelease | None:
    """The single fail-closed source of truth. No session or any error means closed."""
    if db is None:
        return None
    try:
        moment = at or utcnow()
        if not real_beta_requested() or not allowed_families() or not technical_prerequisites_ready():
            return None
        releases = db.scalars(select(RealBetaRelease).where(RealBetaRelease.status == "OPEN")).all()
        if len(releases) != 1:
            return None
        release = releases[0]
        if not _valid_scope(release, moment) or not _approved(db, release, moment):
            return None
        return release
    except Exception:
        return None


def real_beta_gate_open(db: Session | None = None) -> bool:
    return eligible_release(db) is not None


def admission_active(db: Session, user_id: str, at: datetime | None = None) -> bool:
    try:
        moment = at or utcnow()
        release = eligible_release(db, moment)
        if release is None or user_id not in release.cohort_user_ids_json:
            return False
        invitations = db.scalars(select(RealBetaInvitation).where(
            RealBetaInvitation.release_id == release.id,
            RealBetaInvitation.intended_user_id == user_id,
            RealBetaInvitation.accepted_by_user_id == user_id,
            RealBetaInvitation.status == "ACCEPTED",
            RealBetaInvitation.revoked_at.is_(None),
        )).all()
        # expires_at limits only how long an ISSUED invitation secret can be
        # accepted. Once accepted, release eligibility, cohort membership and
        # explicit revocation govern the membership lifecycle.
        return bool(invitations)
    except Exception:
        return False


def audit_once(db: Session, case_id: str | None, event_type: str, payload: dict) -> bool:
    rows = db.scalars(select(AuditEvent).where(
        AuditEvent.case_id == case_id,
        AuditEvent.event_type == event_type,
    )).all()
    if any(row.payload_json == payload for row in rows):
        return False
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload))
    return True


def require_real_case_mutation(db: Session, case: Case) -> None:
    if case.mode != REAL_MODE:
        return
    release = eligible_release(db)
    if release is None or case.real_beta_release_id != release.id:
        raise HTTPException(403, "Private access is unavailable")
    if case.family not in release.families_json:
        raise HTTPException(403, "Private access is unavailable")
    if not case.user_id or not admission_active(db, case.user_id):
        raise HTTPException(403, "Private access is unavailable")
