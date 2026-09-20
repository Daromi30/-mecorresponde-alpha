from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterator

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CompanyResponseEvidence:
    received_on: date | None
    channel: str
    reference_number: str | None


@dataclass(frozen=True)
class OutcomeEvidence:
    resolved_on: date | None
    non_monetary_result: str | None
    resolution_channel: str | None


_COMPANY_RESPONSE_EVIDENCE: ContextVar[CompanyResponseEvidence | None] = ContextVar(
    "mcr_company_response_evidence",
    default=None,
)
_OUTCOME_EVIDENCE: ContextVar[OutcomeEvidence | None] = ContextVar(
    "mcr_outcome_evidence",
    default=None,
)


def current_company_response_evidence() -> CompanyResponseEvidence | None:
    return _COMPANY_RESPONSE_EVIDENCE.get()


def current_outcome_evidence() -> OutcomeEvidence | None:
    return _OUTCOME_EVIDENCE.get()


@contextmanager
def company_response_evidence_context(
    *,
    received_on: date | None,
    channel: str,
    reference_number: str | None,
) -> Iterator[None]:
    token = _COMPANY_RESPONSE_EVIDENCE.set(
        CompanyResponseEvidence(
            received_on=received_on,
            channel=channel,
            reference_number=reference_number,
        )
    )
    try:
        yield
    finally:
        _COMPANY_RESPONSE_EVIDENCE.reset(token)


@contextmanager
def outcome_evidence_context(
    *,
    resolved_on: date | None,
    non_monetary_result: str | None,
    resolution_channel: str | None,
) -> Iterator[None]:
    token = _OUTCOME_EVIDENCE.set(
        OutcomeEvidence(
            resolved_on=resolved_on,
            non_monetary_result=non_monetary_result,
            resolution_channel=resolution_channel,
        )
    )
    try:
        yield
    finally:
        _OUTCOME_EVIDENCE.reset(token)


@contextmanager
def atomic_workflow_transaction(db: Session) -> Iterator[Callable[[], None]]:
    """Defer workflow-internal commits until one outer evidenced-operation commit.

    The resolution engine contains mature service functions that commit at intermediate
    lifecycle boundaries. Evidenced endpoints need stronger atomicity because the state
    transition and the user's real-world evidence are one logical operation. For the duration
    of this context, internal commits become flushes; callers receive the original commit
    method and invoke it exactly once after the workflow finishes successfully.
    """
    real_commit = db.commit

    def flush_instead_of_commit() -> None:
        db.flush()

    db.commit = flush_instead_of_commit  # type: ignore[method-assign]
    try:
        yield real_commit
    except Exception:
        db.rollback()
        raise
    finally:
        db.commit = real_commit  # type: ignore[method-assign]
