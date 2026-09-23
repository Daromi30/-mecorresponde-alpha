from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .calendar_clock import spain_today
from .fact_validation import normalize_user_fact_key


class CaseCreate(BaseModel):
    message: str = Field(min_length=3, max_length=10000)


class FactUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=160)
    value: Any
    state: Literal["asserted", "confirmed", "unknown"] = "asserted"
    materiality: Literal["critical", "relevant", "context"] = "critical"
    confidence: float | None = Field(default=None, ge=0, le=1)
    user_confirmed: bool = True
    correction: bool = False

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return normalize_user_fact_key(value)


class DocumentFactConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=160)
    value: Any
    locator: str | None = Field(default=None, max_length=255)
    excerpt: str | None = Field(default=None, max_length=10000)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return normalize_user_fact_key(value)


class ChargeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float = Field(ge=0)
    service_period_start: date | None = None
    service_period_end: date | None = None
    charged_at: date | None = None
    # Evidence must be asserted explicitly. Omitting this field must never make a
    # user-entered charge look documented by default.
    evidence_verified: bool = False


class ChargesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    charges: list[ChargeInput]


class SubmissionInput(BaseModel):
    submitted_on: date
    channel: str = Field(default="web", min_length=2, max_length=30)
    reference_number: str | None = Field(default=None, max_length=100)

    @field_validator("submitted_on")
    @classmethod
    def reject_future_submission_date(cls, value: date) -> date:
        if value > spain_today():
            raise ValueError("Submission date cannot be in the future")
        return value


class ResponseInput(BaseModel):
    text: str = Field(min_length=3, max_length=30000)


class OutcomeInput(BaseModel):
    result_type: str
    amount_recovered: float | None = None
    verified_by_user: bool = False


class DiagnosisOut(BaseModel):
    viability: str
    scope_status: str
    economic_value: float | None = None
    claimable_amount: float | None
    worth_pursuing: str
    reasoning_summary: str
    counterarguments: list[dict[str, Any]]
    missing_facts: list[str]
    next_action: str
    sources: list[dict[str, str]]
    remedies: list[str] = []
    burden_of_proof: list[dict[str, Any]] = []


class CaseOut(BaseModel):
    id: str
    status: str
    vertical: str | None
    family: str | None
    title: str | None
    raw_intake: str | None
    current_decision_id: str | None
    current_action_id: str | None
    opened_at: datetime
    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    deadlines: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
