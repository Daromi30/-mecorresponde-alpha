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
    """Return false until exact-version professional evidence is modelled.

    ``reviewed_by`` is legacy free text. It is neither an authenticated legal
    authority nor verifiable evidence and therefore cannot open a real-data
    path. A future professional workflow must bind its evidence to the exact
    rule-version id before this predicate can return true.
    """
    return False


def allowed_for_case(rule: Any, case: Any) -> bool:
    """Only the explicit synthetic mode may execute an unapproved rule."""
    return getattr(case, "mode", None) == "SYNTHETIC" and technically_executable(rule)
