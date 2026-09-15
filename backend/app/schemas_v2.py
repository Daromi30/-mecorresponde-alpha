from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from .schemas import CaseCreate, ChargesInput, FactUpsert, OutcomeInput, ResponseInput, SubmissionInput


class DocumentFactConfirm(BaseModel):
    key: str
    value: Any
    locator: str | None = None
    excerpt: str | None = None
    materiality: str = "critical"


class HumanReviewComplete(BaseModel):
    reviewer_decision: str = Field(min_length=3, max_length=10000)


__all__ = [
    "CaseCreate", "ChargesInput", "FactUpsert", "OutcomeInput", "ResponseInput", "SubmissionInput",
    "DocumentFactConfirm", "HumanReviewComplete",
]
