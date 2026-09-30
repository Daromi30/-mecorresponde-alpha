"""Durable SQL intentions for document object writes and post-commit deletion."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .document_storage_lock import document_key_lock
from .models import Document, DocumentStorageOperation
from .storage import DocumentStorage, ObjectProbe, get_document_storage

logger = logging.getLogger(__name__)

PUT = "PUT"
DELETE = "DELETE"
PENDING = "PENDING"
CLEANUP = "CLEANUP"
RETRY = "RETRY"
BLOCKED = "BLOCKED"
COMPLETE = "COMPLETE"
ACTIVE = (PENDING, CLEANUP, RETRY)
_ALLOWED = {
    PENDING: {CLEANUP, RETRY, BLOCKED, COMPLETE},
    CLEANUP: {RETRY, BLOCKED, COMPLETE},
    RETRY: {CLEANUP, RETRY, BLOCKED, COMPLETE},
    BLOCKED: set(),
    COMPLETE: set(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _transition(operation: DocumentStorageOperation, state: str, *, at: datetime) -> None:
    if state not in _ALLOWED.get(operation.state, set()):
        raise RuntimeError("Invalid document storage operation transition")
    operation.state = state
    operation.updated_at = at
    operation.completed_at = at if state == COMPLETE else None
    operation.next_attempt_at = None if state != RETRY else operation.next_attempt_at
    if state == COMPLETE:
        operation.last_error_type = None


def _safe_error_type(exc: BaseException) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)[:80] or "Error"


def create_put_intent(db: Session, *, key: str, sha256: str, backend: str, case_id: str) -> DocumentStorageOperation:
    """Commit before a caller may mutate storage; never holds document bytes."""
    operation = DocumentStorageOperation(
        operation_type=PUT, storage_key=key, sha256=sha256, backend=backend,
        state=PENDING, cleanup_allowed=False, case_id=case_id,
    )
    db.add(operation)
    db.commit()
    return operation


def authorize_put_after_missing_probe(db: Session, operation: DocumentStorageOperation) -> None:
    """A durable may-create marker precedes a potentially ambiguous PUT."""
    if operation.operation_type != PUT or operation.state != PENDING or operation.cleanup_allowed:
        raise RuntimeError("Invalid PUT authorization")
    operation.cleanup_allowed = True
    operation.updated_at = _utcnow()
    db.commit()


def complete_put_with_document(operation: DocumentStorageOperation, document: Document) -> None:
    """Call inside the same SQL transaction that inserts Document."""
    if operation.operation_type != PUT or operation.storage_key != document.storage_key:
        raise RuntimeError("PUT intent does not match document")
    operation.document_id = document.id
    _transition(operation, COMPLETE, at=_utcnow())


def add_delete_tombstones(db: Session, documents: list[Document], *, backend: str) -> list[str]:
    """Flush these in the same transaction as logical case/account deletion."""
    ids: list[str] = []
    seen: dict[str, str] = {}
    for document in documents:
        if document.storage_key in seen:
            if seen[document.storage_key] != document.sha256:
                raise RuntimeError("Conflicting document hashes for one storage key")
            continue
        seen[document.storage_key] = document.sha256
        operation = DocumentStorageOperation(
            operation_type=DELETE, storage_key=document.storage_key,
            sha256=document.sha256, backend=backend, state=CLEANUP,
            cleanup_allowed=True, case_id=document.case_id, document_id=document.id,
        )
        db.add(operation)
        db.flush()
        ids.append(operation.id)
    return ids


def _probe(storage: DocumentStorage, key: str, sha256: str) -> ObjectProbe:
    # Compatibility for in-memory test doubles; production backends implement
    # probe_object and can verify provider metadata as well as bytes.
    method = getattr(storage, "probe_object", None)
    if method is not None:
        try:
            result = method(key, sha256)
            return ObjectProbe(result)
        except Exception:
            return ObjectProbe.UNKNOWN
    try:
        data = storage.get_bytes(key)
    except FileNotFoundError:
        return ObjectProbe.MISSING
    except Exception:
        return ObjectProbe.UNKNOWN
    return (ObjectProbe.PRESENT_AND_VALID if hashlib.sha256(data).hexdigest() == sha256
            else ObjectProbe.PRESENT_CONFLICTING)


def _retry(operation: DocumentStorageOperation, at: datetime, error_type: str) -> None:
    _transition(operation, RETRY, at=at)
    delay = min(3600, 2 ** min(operation.attempt_count, 12))
    operation.next_attempt_at = at + timedelta(seconds=delay)
    operation.last_error_type = error_type


def _blocked(operation: DocumentStorageOperation, at: datetime, error_type: str) -> None:
    _transition(operation, BLOCKED, at=at)
    operation.last_error_type = error_type


def _process_locked(db: Session, operation: DocumentStorageOperation, storage: DocumentStorage, at: datetime) -> None:
    operation.attempt_count += 1
    if operation.operation_type not in {PUT, DELETE} or (operation.operation_type == DELETE and not operation.cleanup_allowed):
        _blocked(operation, at, "InvalidOperation")
        return
    if operation.backend != storage.backend_name:
        _blocked(operation, at, "BackendMismatch")
        return
    references = list(db.scalars(select(Document).where(Document.storage_key == operation.storage_key)).all())
    probe = _probe(storage, operation.storage_key, operation.sha256)
    if references:
        if any(document.sha256 != operation.sha256 for document in references) or probe != ObjectProbe.PRESENT_AND_VALID:
            if probe == ObjectProbe.UNKNOWN:
                _retry(operation, at, "ProbeUnavailable")
            else:
                _blocked(operation, at, "ReferencedObjectIntegrity")
            return
        _transition(operation, COMPLETE, at=at)
        return
    if probe == ObjectProbe.MISSING:
        _transition(operation, COMPLETE, at=at)
        return
    if probe == ObjectProbe.PRESENT_CONFLICTING:
        _blocked(operation, at, "ObjectIntegrity")
        return
    if probe == ObjectProbe.UNKNOWN:
        _retry(operation, at, "ProbeUnavailable")
        return
    if operation.operation_type == PUT and not operation.cleanup_allowed:
        # This object predates the attempted PUT. Do not claim or delete it.
        _transition(operation, COMPLETE, at=at)
        return
    if operation.state != CLEANUP:
        _transition(operation, CLEANUP, at=at)
    try:
        storage.delete_bytes(operation.storage_key)
    except Exception as exc:
        _retry(operation, at, _safe_error_type(exc))
        return
    after = _probe(storage, operation.storage_key, operation.sha256)
    if after == ObjectProbe.MISSING:
        _transition(operation, COMPLETE, at=at)
    elif after == ObjectProbe.PRESENT_CONFLICTING:
        _blocked(operation, at, "PostDeleteIntegrity")
    else:
        _retry(operation, at, "DeleteNotConfirmed")


def reconcile_document_storage_operations(
    db: Session, *, storage: DocumentStorage | None = None, limit: int = 20,
    operation_ids: list[str] | None = None, at: datetime | None = None,
) -> dict[str, int]:
    """Process a bounded batch. PostgreSQL row locks and key locks cover I/O."""
    if not 1 <= limit <= 100:
        raise ValueError("Reconciliation limit must be 1..100")
    storage = storage or get_document_storage()
    at = at or _utcnow()
    bind = db.get_bind()
    result = {"attempted": 0, "completed": 0, "retry": 0, "blocked": 0}
    with Session(bind) as listing:
        query = select(DocumentStorageOperation.id, DocumentStorageOperation.storage_key).where(
            DocumentStorageOperation.state.in_(ACTIVE),
            (DocumentStorageOperation.next_attempt_at.is_(None) | (DocumentStorageOperation.next_attempt_at <= at)),
        )
        if operation_ids is not None:
            query = query.where(DocumentStorageOperation.id.in_(operation_ids))
        candidates = listing.execute(query.order_by(DocumentStorageOperation.created_at, DocumentStorageOperation.id).limit(limit)).all()
    for operation_id, key in candidates:
        with document_key_lock(db, key):
            with Session(bind, autoflush=False) as work:
                query = select(DocumentStorageOperation).where(DocumentStorageOperation.id == operation_id)
                if bind.dialect.name == "postgresql":
                    query = query.with_for_update(skip_locked=True)
                operation = work.scalar(query)
                if operation is None or operation.state not in ACTIVE:
                    continue
                if operation.next_attempt_at is not None:
                    due = operation.next_attempt_at
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due > at:
                        continue
                try:
                    _process_locked(work, operation, storage, at)
                    state = operation.state
                    work.commit()
                except Exception as exc:
                    work.rollback()
                    logger.error("DOCUMENT_STORAGE_RECONCILIATION_ERROR operation_id=%s error_type=%s", operation_id, _safe_error_type(exc))
                    continue
                result["attempted"] += 1
                result[{COMPLETE: "completed", RETRY: "retry", BLOCKED: "blocked"}[state]] += 1
                log = logger.warning if state in {RETRY, BLOCKED} else logger.info
                log("DOCUMENT_STORAGE_RECONCILED operation_id=%s type=%s state=%s backend=%s attempt=%s error_type=%s",
                    operation.id, operation.operation_type, state, operation.backend,
                    operation.attempt_count, operation.last_error_type)
    return result


def document_storage_operation_status(db: Session, *, at: datetime | None = None) -> dict[str, int]:
    """Internal counts only; no keys or content leave this boundary."""
    at = at or _utcnow()
    counts = {state.lower(): 0 for state in (PENDING, CLEANUP, RETRY, BLOCKED)}
    for state, count in db.execute(
        select(DocumentStorageOperation.state, func.count()).where(
            DocumentStorageOperation.state.in_((PENDING, CLEANUP, RETRY, BLOCKED))
        ).group_by(DocumentStorageOperation.state)
    ):
        counts[state.lower()] = count
    counts["completed_recent"] = db.scalar(
        select(func.count()).select_from(DocumentStorageOperation).where(
            DocumentStorageOperation.state == COMPLETE,
            DocumentStorageOperation.completed_at >= at - timedelta(days=1),
        )
    ) or 0
    return counts


def cleanup_committed_tombstones(db: Session, storage: DocumentStorage, operation_ids: list[str]) -> bool:
    """Best-effort inline cleanup after SQL commit; True means still pending."""
    if not operation_ids:
        return False
    try:
        reconcile_document_storage_operations(
            db, storage=storage, operation_ids=operation_ids, limit=min(len(operation_ids), 100),
        )
    except Exception as exc:
        logger.error("DOCUMENT_STORAGE_INLINE_CLEANUP_ERROR error_type=%s", _safe_error_type(exc))
        return True
    try:
        with Session(db.get_bind()) as check:
            remaining = check.scalar(
                select(func.count()).select_from(DocumentStorageOperation).where(
                    DocumentStorageOperation.id.in_(operation_ids),
                    DocumentStorageOperation.state != COMPLETE,
                )
            ) or 0
        return remaining > 0
    except Exception as exc:
        logger.error("DOCUMENT_STORAGE_CLEANUP_STATUS_ERROR error_type=%s", _safe_error_type(exc))
        return True
