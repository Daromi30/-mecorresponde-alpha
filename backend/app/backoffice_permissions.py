"""Small, explicit permission matrix for individual backoffice principals."""

from __future__ import annotations

from .auth_models import Reviewer


MANAGE_REVIEWERS = "manage_reviewers"
MANAGE_TECHNICAL_SCOPE = "manage_technical_scope"
ASSIGN_REVIEWS = "assign_reviews"
VIEW_ALL_CASES = "view_all_cases"
WORK_ASSIGNED_CASES = "work_assigned_cases"

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "operator": frozenset({
        MANAGE_REVIEWERS,
        MANAGE_TECHNICAL_SCOPE,
        ASSIGN_REVIEWS,
        VIEW_ALL_CASES,
    }),
    "reviewer": frozenset({WORK_ASSIGNED_CASES}),
}


def capabilities_for_role(role: str) -> frozenset[str]:
    """Unknown roles deliberately receive no capability."""
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(reviewer: Reviewer | None, capability: str) -> bool:
    return bool(
        reviewer is not None
        and reviewer.disabled_at is None
        and capability in capabilities_for_role(reviewer.role)
    )
