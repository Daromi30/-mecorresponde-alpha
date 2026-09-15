from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from ..auth_throttle import login_throttle
from ..db import get_db
from ..models import Case

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthCredentials(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = normalize_email(value)
        if not value or len(value) > 320 or " " in value or value.count("@") != 1:
            raise ValueError("Use a valid email address")
        local, domain = value.rsplit("@", 1)
        if not local or not domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Use a valid email address")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError("Password must contain at least 10 characters")
        if len(value) > 128:
            raise ValueError("Password is too long")
        return value


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
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
    return {"user": user_payload(user)}


@router.post("/login")
def login(
    payload: AuthCredentials,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(payload.email)
    login_throttle.check(email)
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        # Spend roughly the same password-derivation work as a real lookup so
        # a missing account is less obvious from response timing.
        hash_password(payload.password)
        login_throttle.fail(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.disabled_at is not None or not verify_password(payload.password, user.password_hash):
        login_throttle.fail(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    login_throttle.success(email)
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
