"""Private admission endpoints; never exposed as an alternative public intake."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..admin_auth import AdminPrincipal, require_admin
from ..auth import require_current_user
from ..auth_models import RealBetaInvitation, User
from ..db import get_db
from ..real_beta_gate import (
    REAL_MODE, admission_active, allowed_families, audit_once,
    real_beta_gate_open, utcnow,
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


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=32, max_length=256)


class PrivateCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=3, max_length=500)
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
    # The secret is returned only at issuance. Delivery is deliberately out of scope.
    token = secrets.token_urlsafe(32)
    invitation = RealBetaInvitation(
        token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        status="ISSUED",
        expires_at=utcnow() + timedelta(hours=payload.expires_in_hours),
    )
    db.add(invitation)
    db.flush()
    audit(db, None, "REAL_BETA_INVITE_CREATED", {"invitation_id": invitation.id}, actor_reviewer_id=principal.actor_id)
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
    if not real_beta_gate_open():
        audit_once(db, None, "REAL_BETA_ADMISSION_DENIED", {"user_id": user.id, "reason": "gate_closed"})
        db.commit()
        raise HTTPException(404, "Private access unavailable")
    digest = hashlib.sha256(payload.token.get_secret_value().encode("utf-8")).hexdigest()
    moment = utcnow()
    # One conditional UPDATE is the linearization point. A competing account or
    # repeated request cannot accept a row that has ceased to be ISSUED.
    result = db.execute(
        update(RealBetaInvitation)
        .where(
            RealBetaInvitation.token_digest == digest,
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
    if not real_beta_gate_open() or not admission_active(db, user.id):
        audit_once(db, None, "REAL_BETA_ADMISSION_DENIED", {"user_id": user.id, "reason": "case_creation_unavailable"})
        db.commit()
        raise HTTPException(403, "Private access unavailable")
    try:
        # Reuse the existing atomic creation wrapper. Its intermediate commits are
        # flushes; a family rejection rolls the raw intake back before durability.
        case = cases_v2.create_case(db, payload.message)
        if case.family not in allowed_families():
            family = case.family or "UNCLASSIFIED"
            db.rollback()
            audit_once(db, None, "REAL_BETA_FAMILY_BLOCKED", {"user_id": user.id, "family": family})
            db.commit()
            raise HTTPException(403, "Private access unavailable")
        case.mode = REAL_MODE
        case.user_id = user.id
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
