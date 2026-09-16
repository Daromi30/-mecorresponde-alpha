from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..account_export import build_account_export
from ..account_lifecycle import AccountDeletionStorageError, delete_account_and_owned_data
from ..account_tokens import (
    PASSWORD_RESET,
    PASSWORD_RESET_TTL,
    VERIFY_EMAIL,
    VERIFY_EMAIL_TTL,
    consume_action_token,
    issue_action_token,
    revoke_all_sessions,
)
from ..auth import (
    clear_session_cookie,
    get_session_from_request,
    hash_password,
    issue_session,
    normalize_email,
    require_current_user,
    verify_password,
)
from ..auth_models import User
from ..auth_throttle import (
    login_throttle,
    password_reset_throttle,
    verification_email_throttle,
)
from ..config import settings
from ..db import get_db
from ..email_delivery import (
    EmailDeliveryFailed,
    EmailDeliveryUnavailable,
    action_link,
    send_transactional_email,
)
from ..models import Case

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("uvicorn.error")
MIN_RESET_REQUEST_SECONDS = 0.4


def _validate_email(value: str) -> str:
    value = normalize_email(value)
    if not value or len(value) > 320 or " " in value or value.count("@") != 1:
        raise ValueError("Use a valid email address")
    local, domain = value.rsplit("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Use a valid email address")
    return value


def _validate_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must contain at least 10 characters")
    if len(value) > 128:
        raise ValueError("Password is too long")
    return value


class AuthCredentials(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class EmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=10, max_length=128)
    confirmation: Literal["DELETE"]


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
    }


def _require_operational_email() -> None:
    if not settings.transactional_email_operational:
        raise HTTPException(
            status_code=503,
            detail="Account verification and recovery email is not available yet",
        )


def _minimum_reset_response_time(started: float) -> None:
    remaining = MIN_RESET_REQUEST_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


@router.get("/capabilities")
def auth_capabilities():
    operational = settings.transactional_email_operational
    verification_enforced = bool(settings.email_verification_enforced and operational)
    return {
        "transactional_email_operational": operational,
        "password_recovery_available": operational,
        "email_verification_available": operational,
        "email_verification_enforced": verification_enforced,
    }


@router.post("/register", status_code=201)
def register(
    payload: AuthCredentials,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(payload.email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="An account already exists for this email")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    issue_session(db, user, response)
    db.commit()
    return {
        "user": user_payload(user),
        "email_verification_required": bool(
            settings.email_verification_enforced and settings.transactional_email_operational
        ),
    }


@router.post("/login")
def login(
    payload: AuthCredentials,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(payload.email)
    login_throttle.check(db, email)
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        hash_password(payload.password)
        login_throttle.fail(db, email)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.disabled_at is not None or not verify_password(payload.password, user.password_hash):
        login_throttle.fail(db, email)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    login_throttle.success(db, email)
    issue_session(db, user, response)
    db.commit()
    return {"user": user_payload(user)}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    session = get_session_from_request(request, db)
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me")
def me(user: User = Depends(require_current_user)):
    return {"user": user_payload(user)}


@router.post("/email-verification/request", status_code=202)
def request_email_verification(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    if user.email_verified_at is not None:
        return {"status": "already_verified"}
    _require_operational_email()
    verification_email_throttle.check(db, user.email)

    token = issue_action_token(db, user, purpose=VERIFY_EMAIL, ttl=VERIFY_EMAIL_TTL)
    link = action_link("verify-email", token)
    try:
        send_transactional_email(
            to_email=user.email,
            subject="Verifica tu email de MECORRESPONDE",
            text=(
                "Verifica que este email te pertenece abriendo este enlace:\n\n"
                f"{link}\n\n"
                "El enlace caduca en 24 horas y deja de funcionar al usarlo o pedir uno nuevo. "
                "Si no has creado una cuenta en MECORRESPONDE, ignora este mensaje."
            ),
        )
    except (EmailDeliveryFailed, EmailDeliveryUnavailable) as exc:
        db.rollback()
        logger.warning("MECORRESPONDE verification email delivery failed")
        raise HTTPException(status_code=503, detail="Verification email could not be sent") from exc
    verification_email_throttle.hit(db, user.email)
    db.commit()
    return {"status": "sent"}


@router.post("/email-verification/confirm")
def confirm_email_verification(payload: TokenRequest, db: Session = Depends(get_db)):
    consumed = consume_action_token(db, payload.token, purpose=VERIFY_EMAIL)
    if not consumed:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    _, user = consumed
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    verification_email_throttle.success(db, user.email)
    db.commit()
    return {"status": "verified", "user": user_payload(user)}


@router.post("/password-reset/request", status_code=202)
def request_password_reset(payload: EmailRequest, db: Session = Depends(get_db)):
    _require_operational_email()
    started = time.monotonic()
    email = normalize_email(payload.email)
    password_reset_throttle.check(db, email)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.disabled_at is None:
        token = issue_action_token(db, user, purpose=PASSWORD_RESET, ttl=PASSWORD_RESET_TTL)
        link = action_link("reset-password", token)
        try:
            send_transactional_email(
                to_email=user.email,
                subject="Restablece tu contraseña de MECORRESPONDE",
                text=(
                    "Se ha solicitado restablecer la contraseña de tu cuenta. Abre este enlace:\n\n"
                    f"{link}\n\n"
                    "El enlace caduca en 30 minutos y deja de funcionar al usarlo o pedir uno nuevo. "
                    "Si no has solicitado este cambio, ignora este mensaje."
                ),
            )
        except (EmailDeliveryFailed, EmailDeliveryUnavailable):
            db.rollback()
            logger.warning("MECORRESPONDE password reset email delivery failed")
    password_reset_throttle.hit(db, email)
    db.commit()
    _minimum_reset_response_time(started)
    return {
        "status": "accepted",
        "message": "Si existe una cuenta para ese email, recibirá instrucciones de recuperación.",
    }


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirm,
    response: Response,
    db: Session = Depends(get_db),
):
    consumed = consume_action_token(db, payload.token, purpose=PASSWORD_RESET)
    if not consumed:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset link")
    _, user = consumed
    user.password_hash = hash_password(payload.password)
    revoke_all_sessions(db, user)
    password_reset_throttle.success(db, user.email)
    db.commit()
    clear_session_cookie(response)
    return {"status": "password_updated"}


@router.get("/cases")
def my_cases(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    cases = db.scalars(
        select(Case).where(Case.user_id == user.id).order_by(Case.updated_at.desc())
    ).all()
    return {
        "cases": [
            {
                "id": case.id,
                "status": case.status,
                "vertical": case.vertical,
                "family": case.family,
                "title": case.title,
                "opened_at": case.opened_at,
                "updated_at": case.updated_at,
            }
            for case in cases
        ]
    }


@router.get("/export")
def export_account_data(
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Content-Disposition"] = 'attachment; filename="mecorresponde-export.json"'
    response.headers["Cache-Control"] = "no-store"
    return build_account_export(db, user)


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    login_throttle.check(db, user.email)
    if not verify_password(payload.password, user.password_hash):
        login_throttle.fail(db, user.email)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    login_throttle.success(db, user.email)

    try:
        result = delete_account_and_owned_data(db, user)
    except AccountDeletionStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Account deletion could not safely remove stored documents; no deletion was committed",
        ) from exc

    clear_session_cookie(response)
    return {
        "status": "deleted",
        "cases_deleted": result.cases_deleted,
        "documents_deleted": result.documents_deleted,
    }
