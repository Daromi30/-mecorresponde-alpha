from __future__ import annotations

from dataclasses import dataclass

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
