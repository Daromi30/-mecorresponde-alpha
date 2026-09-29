"""Closed-by-default, server-owned admission boundary for a future private beta.

This is deliberately not a launch approval. The public synthetic intake remains open,
so real-person data must not be accepted until its separate operational/privacy gates
and backoffice attribution are built and independently approved.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import RealBetaInvitation
from .config import settings
from .db import engine
from .family_manifest import FAMILY_MANIFEST
from .models import AuditEvent, Case
from .privacy_information import privacy_information_status
from .storage import StorageConfigurationError, storage_status


# A future, reviewed engineering block must replace this interlock after the
# public synthetic boundary, individual backoffice identity and operations exist.
# No environment variable can override it in this PR.
REAL_BETA_LAUNCH_REVIEW_COMPLETE = False
REAL_MODE = "PRIVATE_REAL_BETA"
SYNTHETIC_MODE = "SYNTHETIC"


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def real_beta_requested() -> bool:
    return isinstance(settings.real_beta_enabled, str) and settings.real_beta_enabled.strip().casefold() == "true"


def allowed_families() -> frozenset[str]:
    raw = settings.real_beta_allowlist
    if not isinstance(raw, str) or not raw.strip():
        return frozenset()
    values = [part.strip() for part in raw.split(",")]
    if any(not value or value not in FAMILY_MANIFEST for value in values):
        return frozenset()
    return frozenset(values)


def technical_prerequisites_ready() -> bool:
    if not REAL_BETA_LAUNCH_REVIEW_COMPLETE:
        return False
    if engine.dialect.name != "postgresql" or not privacy_information_status(settings).ready:
        return False
    if not settings.transactional_email_operational:
        return False
    try:
        return storage_status().persistent
    except StorageConfigurationError:
        return False


def real_beta_gate_open() -> bool:
    return real_beta_requested() and bool(allowed_families()) and technical_prerequisites_ready()


def admission_active(db: Session, user_id: str, at: datetime | None = None) -> bool:
    moment = at or utcnow()
    invitations = db.scalars(
        select(RealBetaInvitation).where(
            RealBetaInvitation.accepted_by_user_id == user_id,
            RealBetaInvitation.status == "ACCEPTED",
            RealBetaInvitation.revoked_at.is_(None),
        )
    ).all()
    return any(utc(invitation.expires_at) > moment for invitation in invitations)


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
    if not real_beta_gate_open():
        raise HTTPException(403, "Private access is unavailable")
    if case.family not in allowed_families():
        raise HTTPException(403, "Private access is unavailable")
    if not case.user_id or not admission_active(db, case.user_id):
        raise HTTPException(403, "Private access is unavailable")
