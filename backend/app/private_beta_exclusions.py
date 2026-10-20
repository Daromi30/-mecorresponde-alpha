"""Non-negotiable capability exclusions for PRIVATE_REAL_BETA.

These exclusions are code-owned and deliberately cannot be enabled through
environment configuration, provider presence, user role or release approval.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .auth_models import RealBetaInvitation


PRIVATE_REAL_BETA = "PRIVATE_REAL_BETA"

DOCUMENT_UPLOAD = "document_upload"
EXTERNAL_AI = "external_ai"
AUTOMATIC_EMAIL = "automatic_email"
PAYMENTS = "payments"
LANE3 = "lane3"
EXTERNAL_MONITORING = "external_monitoring"
DOWNLOADABLE_DRAFT = "downloadable_draft"
AUTOMATIC_SUBMISSION = "automatic_submission"
EXTERNAL_ACTION = "external_action"

EXCLUDED_CAPABILITIES = frozenset({
    DOCUMENT_UPLOAD,
    EXTERNAL_AI,
    AUTOMATIC_EMAIL,
    PAYMENTS,
    LANE3,
    EXTERNAL_MONITORING,
    DOWNLOADABLE_DRAFT,
    AUTOMATIC_SUBMISSION,
    EXTERNAL_ACTION,
})


class PrivateRealBetaCapabilityBlocked(RuntimeError):
    pass


def _mode(subject: object) -> str | None:
    return subject if isinstance(subject, str) else getattr(subject, "mode", None)


def capability_allowed(subject: object, capability: str) -> bool:
    """Fail closed for every capability in private-real-beta mode.

    Unknown capabilities are also denied so a newly introduced integration
    cannot become an accidental bypass.
    """
    try:
        if _mode(subject) != PRIVATE_REAL_BETA:
            return True
        return False
    except Exception:
        return False


def require_capability(subject: object, capability: str) -> None:
    if not capability_allowed(subject, capability):
        raise PrivateRealBetaCapabilityBlocked(
            f"{capability} is unavailable for the private beta"
        )


def exclusions_ready() -> bool:
    """Prove the complete policy is closed, including unknown future actions."""
    try:
        return (
            all(not capability_allowed(PRIVATE_REAL_BETA, item) for item in EXCLUDED_CAPABILITIES)
            and not capability_allowed(PRIVATE_REAL_BETA, "unknown_future_external_capability")
        )
    except Exception:
        return False


def user_capability_allowed(db: Session, user_id: str, capability: str) -> bool:
    """Deny excluded capabilities for every accepted private-beta member.

    This membership lookup intentionally does not depend on current release
    eligibility: closing a release must never re-enable an external provider.
    A database/query failure is also a denial.
    """
    if capability not in EXCLUDED_CAPABILITIES:
        return False
    try:
        membership = db.scalar(select(RealBetaInvitation.id).where(
            or_(
                RealBetaInvitation.intended_user_id == user_id,
                RealBetaInvitation.accepted_by_user_id == user_id,
            ),
            RealBetaInvitation.release_id.is_not(None),
        ))
        return membership is None
    except Exception:
        return False
