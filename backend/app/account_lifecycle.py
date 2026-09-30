from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth_models import EmailActionToken, User, UserSession
from .auth_throttle import clear_all_auth_throttles
from .document_storage_reconciliation import add_delete_tombstones, cleanup_committed_tombstones
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
    storage_cleanup_pending: bool = False


def delete_account_and_owned_data(db: Session, user: User) -> AccountDeletionResult:
    """Commit account removal and object tombstones atomically in SQL first."""
    case_ids = list(
        db.scalars(select(Case.id).where(Case.user_id == user.id).with_for_update()).all()
    )
    if not case_ids:
        clear_all_auth_throttles(db, user.email)
        db.execute(delete(EmailActionToken).where(EmailActionToken.user_id == user.id))
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.delete(user)
        db.commit()
        return AccountDeletionResult(cases_deleted=0, documents_deleted=0)

    documents = list(
        db.scalars(select(Document).where(Document.case_id.in_(case_ids))).all()
    )
    try:
        storage = get_document_storage() if documents else None
    except Exception as exc:
        db.rollback()
        raise AccountDeletionStorageError("Could not prepare durable document cleanup") from exc
    tombstone_ids = add_delete_tombstones(db, documents, backend=storage.backend_name) if storage else []
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
    clear_all_auth_throttles(db, user.email)
    db.execute(delete(EmailActionToken).where(EmailActionToken.user_id == user.id))
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.delete(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    pending = cleanup_committed_tombstones(db, storage, tombstone_ids) if storage else False
    return AccountDeletionResult(
        cases_deleted=len(case_ids),
        documents_deleted=len(documents),
        storage_cleanup_pending=pending,
    )
