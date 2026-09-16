from __future__ import annotations

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    message: str = Field(min_length=3, max_length=10000)


class FactUpsert(BaseModel):
    key: str
    value: Any
    state: str = "asserted"
    materiality: str = "critical"
    confidence: float | None = None
    user_confirmed: bool = True


class DocumentFactConfirm(BaseModel):
    key: str
    value: Any
    locator: str | None = None
    excerpt: str | None = None


class ChargeInput(BaseModel):
    amount: float = Field(ge=0)
    service_period_start: date | None = None
    service_period_end: date | None = None
    charged_at: date | None = None
    evidence_verified: bool = True


class ChargesInput(BaseModel):
    charges: list[ChargeInput]


class SubmissionInput(BaseModel):
    submitted_on: date
    channel: str = Field(default="web", min_length=2, max_length=40)
    reference_number: str | None = Field(default=None, max_length=200)


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