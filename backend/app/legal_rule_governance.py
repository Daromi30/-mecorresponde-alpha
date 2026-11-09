"""Separate technical rule execution from professional legal approval."""

from __future__ import annotations

from typing import Any


TECHNICAL_DRAFT = "technical_draft"
PROFESSIONALLY_APPROVED = "approved"
TECHNICALLY_EXECUTABLE_STATUSES = frozenset({TECHNICAL_DRAFT, PROFESSIONALLY_APPROVED})


def technically_executable(rule: Any) -> bool:
    """Whether a version may be exercised with synthetic data."""
    return getattr(rule, "review_status", None) in TECHNICALLY_EXECUTABLE_STATUSES


def professionally_approved(rule: Any) -> bool:
    """Professional approval requires both an explicit state and attribution."""
    return (
        getattr(rule, "review_status", None) == PROFESSIONALLY_APPROVED
        and bool(str(getattr(rule, "reviewed_by", "") or "").strip())
    )


def allowed_for_case(rule: Any, case: Any, *, case_release_approved: bool = False) -> bool:
    """Draft rules need either synthetic scope or an approved case-level release."""
    if getattr(case, "mode", None) != "SYNTHETIC":
        return professionally_approved(rule) or (
            case_release_approved and technically_executable(rule)
        )
    return technically_executable(rule)
