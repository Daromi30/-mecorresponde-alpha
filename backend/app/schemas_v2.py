from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .fact_validation import normalize_user_fact_key
from .schemas import CaseCreate, ChargesInput, FactUpsert, OutcomeInput, ResponseInput, SubmissionInput


class DocumentFactConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=160)
    value: Any
    locator: str | None = Field(default=None, max_length=255)
    excerpt: str | None = Field(default=None, max_length=10000)
    materiality: Literal["critical", "relevant", "context"] = "critical"

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return normalize_user_fact_key(value)


class HumanReviewComplete(BaseModel):
    reviewer_decision: str = Field(min_length=3, max_length=10000)


class CaseDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]


__all__ = [
    "CaseCreate", "ChargesInput", "FactUpsert", "OutcomeInput", "ResponseInput", "SubmissionInput",
    "DocumentFactConfirm", "HumanReviewComplete", "CaseDeleteRequest",
]
