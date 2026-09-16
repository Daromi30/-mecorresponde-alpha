from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    AIRun,
    Action,
    AuditEvent,
    Calculation,
    Case,
    Communication,
    Counterargument,
    Deadline,
    Decision,
    Document,
    DocumentExtraction,
    Evidence,
    Fact,
    Outcome,
    RuleEvaluation,
)
from .reviews import HumanReview
from .security import CaseAccess
from .storage import get_document_storage


class CaseDeletionStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseDeletionResult:
    case_id: str
    documents_deleted: int


def _matches_expected_action_type(action_type: str, only_types: set[str]) -> bool:
    if action_type in only_types:
        return True
    # Engine-generated review actions keep their specific reason in the action type
    # (for example HUMAN_REVIEW_LEGACY or HUMAN_REVIEW_SECOND_HAND). Callers that
    # expect the human-review lifecycle step must close those variants as the same
    # action class, without broadening the match to unrelated workflow actions.
    return "HUMAN_REVIEW" in only_types and action_type.startswith("HUMAN_REVIEW_")


def complete_current_action(
    db: Session,
    case: Case,
    *,
    only_types: set[str] | None = None,
) -> Action | None:
    """Complete the current case action when it belongs to the expected lifecycle step."""
    if not case.current_action_id:
        return None
    action = db.get(Action, case.current_action_id)
    if not action or action.case_id != case.id:
        return None
    if only_types is not None and not _matches_expected_action_type(action.type, only_types):
        return None
    if action.status in {"COMPLETED", "SUPERSEDED"}:
        return action
    action.status = "COMPLETED"
    action.completed_at = datetime.now(timezone.utc)
    return action


def set_current_action(
    db: Session,
    case: Case,
    action_type: str,
    *,
    payload: dict[str, Any] | None = None,
    status: str = "OPEN",
) -> Action:
    """Create the next explicit action and make it the case's current step.

    A case must never acquire a new current action while its previous current action remains
    pending. Centralizing that invariant here protects every workflow transition, including
    structured human-review reanalysis, even when a caller forgets to close its prior step.
    Historical actions are retained and terminal states such as SUPERSEDED are preserved.
    """
    complete_current_action(db, case)
    action = Action(
        case_id=case.id,
        type=action_type,
        status=status,
        payload_json=payload or {},
    )
    db.add(action)
    db.flush()
    case.current_action_id = action.id
    return action


def delete_case_and_data(db: Session, case: Case) -> CaseDeletionResult:
    """Delete one accessible case and its persisted document objects.

    Storage objects are deleted before the database transaction is committed. If
    object deletion fails, the database is rolled back so the application never
    reports a clean deletion while knowingly retaining a document object.
    """
    case_id = case.id
    documents = list(db.scalars(select(Document).where(Document.case_id == case_id)).all())
    if documents:
        try:
            storage = get_document_storage()
            for document in documents:
                storage.delete_bytes(document.storage_key)
        except Exception as exc:
            db.rollback()
            raise CaseDeletionStorageError("Could not remove all stored document objects") from exc

    document_ids = [document.id for document in documents]
    if document_ids:
        db.execute(
            delete(DocumentExtraction).where(DocumentExtraction.document_id.in_(document_ids))
        )

    case_scoped_models = (
        Evidence,
        RuleEvaluation,
        Counterargument,
        Calculation,
        Action,
        Deadline,
        Communication,
        Outcome,
        HumanReview,
        CaseAccess,
        Fact,
        Document,
        Decision,
        AuditEvent,
        AIRun,
    )
    for model in case_scoped_models:
        db.execute(delete(model).where(model.case_id == case_id))

    db.execute(delete(Case).where(Case.id == case_id))
    db.commit()
    return CaseDeletionResult(case_id=case_id, documents_deleted=len(documents))
