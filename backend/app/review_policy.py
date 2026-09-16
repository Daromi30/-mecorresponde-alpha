from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import services_v2 as svc
from .models import Case
from .reviews import HumanReview


_INSTALLED = False


def install_review_policy() -> None:
    """Keep an open review and the case workflow phase synchronized.

    The base helper deduplicates open reviews by case/reason. Reusing that row is correct,
    but the case may have temporarily moved into another internal phase. An OPEN review must
    always remain represented by HUMAN_REVIEW at the case boundary; otherwise the dossier can
    contain a live review that the workflow no longer exposes.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_create_review = svc.create_human_review

    def create_human_review_with_phase_sync(
        db: Session,
        case: Case,
        reason: str,
        priority: str = "NORMAL",
        context: dict[str, Any] | None = None,
    ) -> HumanReview:
        review = previous_create_review(
            db,
            case,
            reason,
            priority=priority,
            context=context,
        )
        if review.status == "OPEN":
            case.status = "HUMAN_REVIEW"
        return review

    svc.create_human_review = create_human_review_with_phase_sync
    _INSTALLED = True
