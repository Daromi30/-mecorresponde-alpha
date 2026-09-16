from __future__ import annotations

import uuid
from datetime import datetime, timezone, date
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="NEW", index=True)
    service_level: Mapped[str] = mapped_column(String(30), default="AUTOMATED_GUIDANCE")
    vertical: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    family: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="ES")
    title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    raw_intake: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(160), index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30), default="asserted")
    materiality: Mapped[str] = mapped_column(String(20), default="relevant")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(20), default="user")
    supersedes_fact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    document_type: Mapped[str] = mapped_column(String(60), default="GENERIC_DOCUMENT")
    processing_status: Mapped[str] = mapped_column(String(30), default="UPLOADED")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contains_sensitive_data: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    extractor_version: Mapped[str] = mapped_column(String(60))
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    fact_id: Mapped[str | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"), nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30))
    locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    strength: Mapped[str] = mapped_column(String(20), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LegalSource(Base):
    __tablename__ = "legal_sources"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    authority: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    official_url: Mapped[str] = mapped_column(String(800))
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="ES")
    status: Mapped[str] = mapped_column(String(30), default="active")


class LegalRuleVersion(Base):
    __tablename__ = "legal_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("legal_sources.id"))
    article: Mapped[str] = mapped_column(String(50))
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    consequence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    interpretation: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(30), default="approved")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    rule_version_id: Mapped[str] = mapped_column(ForeignKey("legal_rule_versions.id"))
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(30))
    missing_conditions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    failed_conditions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    engine_version: Mapped[str] = mapped_column(String(30), default="e04b-1")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Counterargument(Base):
    __tablename__ = "counterarguments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(100))
    origin: Mapped[str] = mapped_column(String(30), default="known_rule")
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    impact: Mapped[str] = mapped_column(String(20), default="material")


class Calculation(Base):
    __tablename__ = "calculations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(80))
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    formula_version: Mapped[str] = mapped_column(String(30))
    result: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    explanation: Mapped[str] = mapped_column(Text)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    viability: Mapped[str] = mapped_column(String(40))
    scope_status: Mapped[str] = mapped_column(String(40), default="SUPPORTED")
    economic_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    claimable_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    worth_pursuing: Mapped[str] = mapped_column(String(40))
    professional_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_summary: Mapped[str] = mapped_column(Text)
    counterarguments_snapshot: Mapped[list[Any]] = mapped_column(JSON, default=list)
    rule_evaluations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Deadline(Base):
    __tablename__ = "deadlines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    deadline_type: Mapped[str] = mapped_column(String(80))
    trigger_event: Mapped[str] = mapped_column(String(100))
    trigger_date: Mapped[date] = mapped_column(Date)
    rule_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    calendar_type: Mapped[str] = mapped_column(String(50), default="BUSINESS_DAYS")
    computed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PROVISIONAL")


class Communication(Base):
    __tablename__ = "communications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(30))
    channel: Mapped[str] = mapped_column(String(30))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), unique=True)
    result_type: Mapped[str] = mapped_column(String(50))
    amount_requested: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_recovered: Mapped[float | None] = mapped_column(Float, nullable=True)
    non_monetary_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(80), default="local")
    model: Mapped[str] = mapped_column(String(100), default="deterministic-alpha")
    prompt_version: Mapped[str] = mapped_column(String(50), default="n/a")
    structured_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
