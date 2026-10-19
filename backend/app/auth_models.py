from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Reviewer(Base):
    """Provisioned backoffice principal; never a claimant User."""

    __tablename__ = "reviewers"
    __table_args__ = (CheckConstraint("role IN ('reviewer', 'operator')", name="ck_reviewer_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    login_id: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class ReviewerFamilyAuthorization(Base):
    """Explicit technical scope; it does not assert legal qualification."""

    __tablename__ = "reviewer_family_authorizations"
    __table_args__ = (UniqueConstraint("reviewer_id", "family", name="uq_reviewer_family_authorization"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("reviewers.id", ondelete="CASCADE"), nullable=False, index=True)
    family: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_by_reviewer_id: Mapped[str] = mapped_column(ForeignKey("reviewers.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class ReviewerSession(Base):
    __tablename__ = "reviewer_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("reviewers.id", ondelete="CASCADE"), index=True, nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class ReleaseAuthority(Base):
    """Out-of-band release authority, deliberately unrelated to Reviewer roles."""

    __tablename__ = "release_authorities"
    __table_args__ = (CheckConstraint(
        "authority_type IN ('OWNER_APPROVER', 'PROFESSIONAL_APPROVER')",
        name="ck_release_authority_type",
    ),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    authority_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RealBetaRelease(Base):
    __tablename__ = "real_beta_releases"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'OPEN', 'CLOSED', 'REVOKED')", name="ck_real_beta_release_status"),
        CheckConstraint("version >= 1", name="ck_real_beta_release_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    families_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cohort_user_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cases_total: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_cases_per_user: Mapped[int] = mapped_column(Integer, nullable=False)
    max_daily_admissions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class ReleaseApproval(Base):
    __tablename__ = "release_approvals"
    __table_args__ = (UniqueConstraint(
        "release_id", "authority_id", "release_version", name="uq_release_approval_authority_version",
    ),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    release_id: Mapped[str] = mapped_column(ForeignKey("real_beta_releases.id", ondelete="RESTRICT"), nullable=False, index=True)
    release_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_id: Mapped[str] = mapped_column(ForeignKey("release_authorities.id", ondelete="RESTRICT"), nullable=False)
    authority_type: Mapped[str] = mapped_column(String(30), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class RealBetaInvitation(Base):
    __tablename__ = "real_beta_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    release_id: Mapped[str | None] = mapped_column(ForeignKey("real_beta_releases.id", ondelete="RESTRICT"), nullable=True, index=True)
    intended_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ISSUED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailActionToken(Base):
    __tablename__ = "email_action_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthThrottleState(Base):
    """Persistent failed-auth state keyed only by a one-way email digest."""

    __tablename__ = "auth_throttle_state"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
