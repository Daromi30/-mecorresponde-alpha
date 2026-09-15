from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth_models import User, UserSession
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


class AccountDeletionStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountDeletionResult:
    cases_deleted: int
    documents_deleted: int


def delete_account_and_owned_data(db: Session, user: User) -> AccountDeletionResult:
    """Delete an account and every case it owns, including non-FK audit/AI rows.

    Document bytes are removed before database records so a storage failure fails closed
    instead of silently leaving personal files behind. Object deletion is idempotent, so
    the operation can safely be retried if the database transaction later fails.
    """
    case_ids = list(
        db.scalars(select(Case.id).where(Case.user_id == user.id)).all()
    )
    if not case_ids:
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.delete(user)
        db.commit()
        return AccountDeletionResult(cases_deleted=0, documents_deleted=0)

    documents = list(
        db.scalars(select(Document).where(Document.case_id.in_(case_ids))).all()
    )
    if documents:
        try:
            storage = get_document_storage()
            for document in documents:
                storage.delete_bytes(document.storage_key)
        except Exception as exc:
            db.rollback()
            raise AccountDeletionStorageError(
                "Could not remove all document objects; account deletion was not committed"
            ) from exc

    document_ids = [document.id for document in documents]
    if document_ids:
        db.execute(
            delete(DocumentExtraction).where(
                DocumentExtraction.document_id.in_(document_ids)
            )
        )

    # Delete explicitly rather than relying only on database cascades. This keeps the
    # behaviour identical in PostgreSQL and the SQLite test environment, and also cleans
    # the intentionally non-FK audit/AI tables.
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
        db.execute(delete(model).where(model.case_id.in_(case_ids)))

    db.execute(delete(Case).where(Case.id.in_(case_ids)))
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.delete(user)
    db.commit()
    return AccountDeletionResult(
        cases_deleted=len(case_ids),
        documents_deleted=len(documents),
    )
