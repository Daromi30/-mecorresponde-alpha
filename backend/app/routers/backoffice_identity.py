"""Reviewer login and operator-only provisioning; no public self-registration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..auth import hash_password, verify_password
from ..auth_models import Reviewer
from ..backoffice_auth import (
    authenticate, clear_cookie, create_reviewer, issue_session, normalize_login,
    require_session, revoke_sessions, session_from_request, utcnow, validate_password,
)
from ..db import get_db
from ..services_v2 import audit


auth_router = APIRouter(prefix="/api/backoffice-auth", tags=["backoffice-auth"])
admin_router = APIRouter(
    prefix="/api/admin/reviewers", tags=["backoffice-reviewers"],
    dependencies=[Depends(require_admin)],
)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str = Field(min_length=1, max_length=120)
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr
    new_password: SecretStr


class ReviewerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str = Field(min_length=3, max_length=120)
    role: str
    initial_password: SecretStr


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: SecretStr


def _operator(request: Request) -> Reviewer:
    principal = getattr(request.state, "admin_principal", None)
    if principal is None or principal.reviewer is None or principal.reviewer.role != "operator":
        raise HTTPException(403, "Operator session required")
    return principal.reviewer


def _target(db: Session, reviewer_id: str) -> Reviewer:
    reviewer = db.get(Reviewer, reviewer_id)
    if reviewer is None:
        raise HTTPException(404, "Reviewer unavailable")
    return reviewer


def _preserve_last_operator(db: Session, target: Reviewer) -> None:
    if target.role != "operator" or target.disabled_at is not None:
        return
    active = db.scalars(select(Reviewer).where(
        Reviewer.role == "operator", Reviewer.disabled_at.is_(None),
    )).all()
    if len(active) <= 1:
        raise HTTPException(409, "At least one active operator is required")


@auth_router.post("/login")
def login(payload: LoginInput, response: Response, db: Session = Depends(get_db)):
    try:
        reviewer = authenticate(db, payload.login_id, payload.password.get_secret_value())
    except HTTPException as exc:
        if exc.status_code == 429:
            audit(db, None, "BACKOFFICE_LOGIN_DENIED", {"reason": "rate_limited"})
            db.commit()
        raise
    if reviewer is None:
        audit(db, None, "BACKOFFICE_LOGIN_DENIED", {"reason": "invalid_credentials"})
        db.commit()
        raise HTTPException(401, "Invalid credentials")
    session = issue_session(db, reviewer, response)
    audit(db, None, "BACKOFFICE_LOGIN_SUCCEEDED", {"session_id": session.id}, actor_reviewer_id=reviewer.id)
    db.commit()
    return {"reviewer_id": reviewer.id, "login_id": reviewer.login_id, "role": reviewer.role}


@auth_router.get("/session")
def session_status(request: Request, db: Session = Depends(get_db)):
    reviewer, session = require_session(request, db)
    return {
        "reviewer_id": reviewer.id, "login_id": reviewer.login_id,
        "role": reviewer.role, "expires_at": session.expires_at,
    }


@auth_router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    resolved = session_from_request(request, db)
    if resolved is not None:
        reviewer, session = resolved
        session.revoked_at = utcnow()
        audit(db, None, "BACKOFFICE_LOGOUT", {"session_id": session.id}, actor_reviewer_id=reviewer.id)
        db.commit()
    clear_cookie(response)
    return {"status": "SIGNED_OUT"}


@auth_router.post("/password")
def change_password(payload: PasswordChange, request: Request, response: Response, db: Session = Depends(get_db)):
    reviewer, _ = require_session(request, db)
    if not verify_password(payload.current_password.get_secret_value(), reviewer.password_hash):
        audit(db, None, "BACKOFFICE_PASSWORD_CHANGE_DENIED", {"reason": "invalid_current"}, actor_reviewer_id=reviewer.id)
        db.commit()
        raise HTTPException(401, "Invalid credentials")
    try:
        new_password = validate_password(payload.new_password.get_secret_value())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if verify_password(new_password, reviewer.password_hash):
        raise HTTPException(422, "New password must differ")
    reviewer.password_hash = hash_password(new_password)
    revoke_sessions(db, reviewer.id)
    audit(db, None, "BACKOFFICE_PASSWORD_CHANGED", {}, actor_reviewer_id=reviewer.id)
    db.commit()
    clear_cookie(response)
    return {"status": "PASSWORD_CHANGED"}


@admin_router.get("")
def list_reviewers(request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    rows = db.scalars(select(Reviewer).order_by(Reviewer.created_at.asc())).all()
    audit(db, None, "BACKOFFICE_REVIEWER_LISTED", {}, actor_reviewer_id=operator.id)
    db.commit()
    return [{"id": row.id, "login_id": row.login_id, "role": row.role, "active": row.disabled_at is None} for row in rows]


@admin_router.post("", status_code=201)
def provision_reviewer(payload: ReviewerCreate, request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    try:
        normalized = normalize_login(payload.login_id)
        validate_password(payload.initial_password.get_secret_value())
        if payload.role not in {"reviewer", "operator"}:
            raise ValueError("Invalid reviewer role")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if db.scalar(select(Reviewer.id).where(Reviewer.login_id == normalized)) is not None:
        raise HTTPException(409, "Reviewer identifier unavailable")
    try:
        reviewer = create_reviewer(db, normalized, payload.initial_password.get_secret_value(), payload.role)
        audit(db, None, "BACKOFFICE_REVIEWER_CREATED", {"target_reviewer_id": reviewer.id, "role": reviewer.role}, actor_reviewer_id=operator.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Reviewer identifier unavailable") from None
    return {"id": reviewer.id, "login_id": reviewer.login_id, "role": reviewer.role}


@admin_router.post("/{reviewer_id}/disable")
def disable_reviewer(reviewer_id: str, request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    target = _target(db, reviewer_id)
    if target.disabled_at is None:
        _preserve_last_operator(db, target)
        target.disabled_at = utcnow()
        revoke_sessions(db, target.id)
        audit(db, None, "BACKOFFICE_REVIEWER_DISABLED", {"target_reviewer_id": target.id}, actor_reviewer_id=operator.id)
        db.commit()
    return {"status": "DISABLED"}


@admin_router.post("/{reviewer_id}/revoke-sessions")
def revoke_reviewer_sessions(reviewer_id: str, request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    target = _target(db, reviewer_id)
    count = revoke_sessions(db, target.id)
    audit(db, None, "BACKOFFICE_SESSIONS_REVOKED", {"target_reviewer_id": target.id, "session_count": count}, actor_reviewer_id=operator.id)
    db.commit()
    return {"status": "REVOKED", "session_count": count}


@admin_router.post("/{reviewer_id}/role")
def change_role(reviewer_id: str, payload: RoleChange, request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    target = _target(db, reviewer_id)
    if payload.role not in {"reviewer", "operator"}:
        raise HTTPException(422, "Invalid reviewer role")
    if target.role != payload.role:
        _preserve_last_operator(db, target)
        target.role = payload.role
        revoke_sessions(db, target.id)
        audit(db, None, "BACKOFFICE_REVIEWER_ROLE_CHANGED", {"target_reviewer_id": target.id, "role": target.role}, actor_reviewer_id=operator.id)
        db.commit()
    return {"id": target.id, "role": target.role}


@admin_router.post("/{reviewer_id}/reset-password")
def reset_reviewer_password(reviewer_id: str, payload: PasswordReset, request: Request, db: Session = Depends(get_db)):
    operator = _operator(request)
    target = _target(db, reviewer_id)
    try:
        new_password = validate_password(payload.new_password.get_secret_value())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    target.password_hash = hash_password(new_password)
    revoke_sessions(db, target.id)
    audit(db, None, "BACKOFFICE_PASSWORD_RESET", {"target_reviewer_id": target.id}, actor_reviewer_id=operator.id)
    db.commit()
    return {"status": "PASSWORD_RESET"}
