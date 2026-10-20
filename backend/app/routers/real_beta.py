"""Private admission endpoints; never exposed as an alternative public intake."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..admin_auth import AdminPrincipal, require_admin
from ..auth import require_current_user
from ..auth_models import RealBetaInvitation, RealBetaRelease, User
from ..db import get_db
from ..family_manifest import FAMILY_MANIFEST
from ..models import Case
from ..real_beta_gate import (
    REAL_MODE, admission_active, audit_once, eligible_release, utc, utcnow,
)
from ..services_v2 import audit
from . import cases_v2


router = APIRouter(prefix="/api/real-beta", tags=["private-real-beta"])
admin_router = APIRouter(
    prefix="/api/admin/real-beta", tags=["private-real-beta-admin"],
    dependencies=[Depends(require_admin)],
)


class InvitationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in_hours: int = Field(ge=1, le=168)
    target_user_id: str = Field(min_length=36, max_length=36)


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=32, max_length=256)


class PrivateCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Literal["E02-A", "C01"]
    age_18_plus_attested: StrictBool

    @field_validator("age_18_plus_attested")
    @classmethod
    def require_adult_attestation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Adult attestation is required")
        return value


@admin_router.post("/invitations", status_code=201)
def issue_invitation(
    payload: InvitationIssue, db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
):
    release = eligible_release(db)
    if (release is None or payload.target_user_id not in release.cohort_user_ids_json
            or db.get(User, payload.target_user_id) is None):
        raise HTTPException(403, "Private access unavailable")
    existing = db.scalars(select(RealBetaInvitation).where(
        RealBetaInvitation.release_id == release.id,
        RealBetaInvitation.intended_user_id == payload.target_user_id,
        RealBetaInvitation.status.in_(("ISSUED", "ACCEPTED")),
        RealBetaInvitation.revoked_at.is_(None),
    )).all()
    if any(item.status == "ACCEPTED" or utc(item.expires_at) > utcnow() for item in existing):
        raise HTTPException(409, "Invitation already exists")
    # The secret is returned only at issuance. Delivery is deliberately out of scope.
    token = secrets.token_urlsafe(32)
    invitation = RealBetaInvitation(
        token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        release_id=release.id,
        intended_user_id=payload.target_user_id,
        status="ISSUED",
        expires_at=utcnow() + timedelta(hours=payload.expires_in_hours),
    )
    db.add(invitation)
    db.flush()
    audit(db, None, "REAL_BETA_INVITE_CREATED", {"invitation_id": invitation.id, "release_id": release.id}, actor_reviewer_id=principal.actor_id)
    db.commit()
    return {"invitation_id": invitation.id, "token": token, "expires_at": invitation.expires_at}


@admin_router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(
    invitation_id: str, db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
):
    invitation = db.scalar(select(RealBetaInvitation).where(RealBetaInvitation.id == invitation_id).with_for_update())
    if invitation is None:
        raise HTTPException(404, "Invitation unavailable")
    if invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        invitation.status = "REVOKED"
        audit(db, None, "REAL_BETA_INVITE_REVOKED", {"invitation_id": invitation.id}, actor_reviewer_id=principal.actor_id)
        db.commit()
    return {"status": "REVOKED"}


@router.post("/invitations/accept")
def accept_invitation(
    payload: InvitationAccept,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    # The release row serializes all admission counters on PostgreSQL.
    locked = db.scalar(select(RealBetaRelease).where(RealBetaRelease.status == "OPEN").with_for_update())
    release = eligible_release(db)
    if release is None or locked is None or release.id != locked.id or user.id not in release.cohort_user_ids_json:
        audit_once(db, None, "REAL_BETA_ADMISSION_DENIED", {"user_id": user.id, "reason": "gate_closed"})
        db.commit()
        raise HTTPException(404, "Private access unavailable")
    accepted = db.scalars(select(RealBetaInvitation).where(
        RealBetaInvitation.release_id == release.id,
        RealBetaInvitation.status == "ACCEPTED",
    )).all()
    today = utcnow().astimezone(timezone.utc).date()
    if (len({item.accepted_by_user_id for item in accepted}) >= release.max_users
            or sum(item.accepted_at is not None and utc(item.accepted_at).date() == today for item in accepted)
            >= release.max_daily_admissions):
        raise HTTPException(404, "Private access unavailable")
    digest = hashlib.sha256(payload.token.get_secret_value().encode("utf-8")).hexdigest()
    moment = utcnow()
    # One conditional UPDATE is the linearization point. A competing account or
    # repeated request cannot accept a row that has ceased to be ISSUED.
    result = db.execute(
        update(RealBetaInvitation)
        .where(
            RealBetaInvitation.token_digest == digest,
            RealBetaInvitation.release_id == release.id,
            RealBetaInvitation.intended_user_id == user.id,
            RealBetaInvitation.status == "ISSUED",
            RealBetaInvitation.revoked_at.is_(None),
            RealBetaInvitation.expires_at > moment,
        )
        .values(status="ACCEPTED", accepted_by_user_id=user.id, accepted_at=moment)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        audit_once(db, None, "REAL_BETA_ADMISSION_DENIED", {"user_id": user.id, "reason": "invalid_invitation"})
        db.commit()
        raise HTTPException(404, "Private access unavailable")
    invitation = db.scalar(select(RealBetaInvitation).where(RealBetaInvitation.token_digest == digest))
    audit(db, None, "REAL_BETA_INVITE_ACCEPTED", {"invitation_id": invitation.id, "user_id": user.id})
    db.commit()
    return {"status": "ACCEPTED"}


@router.post("/cases", status_code=201)
def create_private_case(
    payload: PrivateCaseCreate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    locked = db.scalar(select(RealBetaRelease).where(RealBetaRelease.status == "OPEN").with_for_update())
    release = eligible_release(db)
    if release is None or locked is None or release.id != locked.id or not admission_active(db, user.id):
        audit_once(db, None, "REAL_BETA_ADMISSION_DENIED", {"user_id": user.id, "reason": "case_creation_unavailable"})
        db.commit()
        raise HTTPException(403, "Private access unavailable")
    if payload.family not in release.families_json:
        audit_once(db, None, "REAL_BETA_FAMILY_BLOCKED", {"user_id": user.id, "family": payload.family})
        db.commit()
        raise HTTPException(403, "Private access unavailable")
    existing_cases = db.scalars(select(Case).where(
        Case.mode == REAL_MODE, Case.real_beta_release_id == release.id,
    )).all()
    if (len(existing_cases) >= release.max_cases_total
            or sum(item.user_id == user.id and item.closed_at is None for item in existing_cases)
            >= release.max_active_cases_per_user):
        raise HTTPException(403, "Private access unavailable")
    try:
        entry = FAMILY_MANIFEST[payload.family]
        case = Case(
            status="INTAKE",
            mode=REAL_MODE,
            real_beta_release_id=release.id,
            user_id=user.id,
            vertical=entry.vertical,
            family=entry.code,
            title=entry.title,
            raw_intake=f"{REAL_MODE}:{entry.code}",
        )
        db.add(case)
        db.flush()
        audit(db, case.id, "CASE_STARTED", {
            "admission": "structured_family_selection",
            "family": entry.code,
        })
        audit(db, case.id, "REAL_BETA_ADULT_ATTESTED", {})
        audit(db, case.id, "REAL_BETA_CASE_ADMITTED", {"user_id": user.id, "family": case.family})
        response = {
            **cases_v2.serialize_case(db, case),
            "next_question": cases_v2.get_next_question(db, case),
        }
        db.commit()
        return response
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
