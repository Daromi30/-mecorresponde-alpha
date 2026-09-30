from __future__ import annotations

import hashlib
import io
import logging
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from pypdf import PdfReader
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import settings
from .models import AuditEvent, Case, Document, DocumentExtraction, Evidence, Fact
from .storage import (
    DocumentStorage, PutResult, StorageWriteError, UnsafeDocumentUpload,
    get_document_storage, object_key, read_verified_document, validate_document_bytes,
)


logger = logging.getLogger(__name__)
_local_key_locks: dict[str, threading.Lock] = {}
_local_key_locks_guard = threading.Lock()


class DocumentUploadPersistenceError(RuntimeError):
    pass


class DocumentUploadCompensationError(DocumentUploadPersistenceError):
    pass


@contextmanager
def _document_key_lock(db: Session, key: str):
    """Serialize same-key uploads through commit/rollback and compensation.

    PostgreSQL's session advisory lock works across app workers. SQLite's local
    lock is sufficient for isolated tests/development, not a production lease.
    """
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        with bind.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
        return
    with _local_key_locks_guard:
        lock = _local_key_locks.setdefault(key, threading.Lock())
    with lock:
        yield


def _compensate_new_object(db: Session, storage: DocumentStorage, key: str) -> None:
    # The key lock is still held. A fresh transaction sees committed references,
    # including a commit that succeeded despite a lost DB acknowledgement.
    with Session(db.get_bind()) as check:
        referenced = check.scalar(select(func.count()).select_from(Document).where(Document.storage_key == key))
    if referenced:
        return
    try:
        storage.delete_bytes(key)
    except Exception as exc:
        logger.error("DOCUMENT_UPLOAD_COMPENSATION_FAILED backend=%s error_type=%s", storage.backend_name, type(exc).__name__)
        raise DocumentUploadCompensationError("Document upload failed and object cleanup failed") from None


def _audit(db: Session, case_id: str, event_type: str, payload: dict[str, Any]) -> None:
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload))


def _enforce_alpha_document_quota(db: Session, case_id: str) -> None:
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    if total >= settings.alpha_max_documents_total:
        raise UnsafeDocumentUpload(
            f"Alpha document quota reached ({settings.alpha_max_documents_total} total documents)"
        )

    case_total = db.scalar(
        select(func.count()).select_from(Document).where(Document.case_id == case_id)
    ) or 0
    if case_total >= settings.alpha_max_documents_per_case:
        raise UnsafeDocumentUpload(
            f"Case document quota reached ({settings.alpha_max_documents_per_case} documents)"
        )


def save_upload(
    db: Session,
    case: Case,
    filename: str,
    content_type: str,
    data: bytes,
    *,
    storage: DocumentStorage | None = None,
):
    canonical_mime = validate_document_bytes(filename, content_type, data)
    storage = storage or get_document_storage()

    digest = hashlib.sha256(data).hexdigest()
    key = object_key(case.id, digest)
    with _document_key_lock(db, key):
        existing = db.scalar(select(Document).where(Document.case_id == case.id, Document.storage_key == key))
        if existing is not None:
            read_verified_document(storage, existing)
            extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == existing.id))
            if extraction is None:
                raise DocumentUploadPersistenceError("Existing document has no extraction record")
            return existing, extraction

        created = False
        try:
            _enforce_alpha_document_quota(db, case.id)
            result: PutResult = storage.put_bytes(key, data, content_type=canonical_mime, sha256=digest)
            created = result.created
            document = Document(
                case_id=case.id, storage_key=key, original_filename=filename,
                mime_type=canonical_mime, sha256=digest,
            )
            db.add(document)
            db.flush()

            raw = ""
            pages = None
            flags: list[str] = []
            extracted: dict[str, Any] = {}
            maintenance = None
            try:
                if canonical_mime == "application/pdf":
                    reader = PdfReader(io.BytesIO(data))
                    pages = len(reader.pages)
                    raw = "\n".join((page.extract_text() or "") for page in reader.pages)
                elif canonical_mime.startswith("text/"):
                    raw = data.decode("utf-8")
                else:
                    flags.append("NO_TEXT_EXTRACTOR_FOR_MIME")
                if raw:
                    amounts = re.findall(r"(\d{1,5}[.,]\d{2})\s*(?:€|EUR)", raw, re.I)
                    if amounts:
                        extracted["possible_amounts"] = [float(value.replace(",", ".")) for value in amounts[:20]]
                    maintenance = re.search(
                        r"(?:mantenimiento|protecci[oó]n|servicio)[^\n€]{0,80}?(\d{1,3}[.,]\d{2})\s*(?:€|EUR)",
                        raw, re.I,
                    )
                    if maintenance:
                        extracted["possible_addon_price"] = float(maintenance.group(1).replace(",", "."))
                document.processing_status = "PROCESSED" if raw else "NEEDS_REVIEW"
                document.page_count = pages
            except Exception as exc:
                # Extraction failure is a retained FAILED document, not an
                # unsafe half-committed upload. SQL/commit failures still abort.
                raw = ""
                extracted = {}
                maintenance = None
                document.processing_status = "FAILED"
                flags.append(type(exc).__name__)

            if maintenance is not None:
                price = extracted["possible_addon_price"]
                candidate = Fact(
                    case_id=case.id, key="electricity.addon.detected_price",
                    value_json={"value": price}, state="inferred", materiality="context",
                    confidence=0.65, user_confirmed=False, created_by="system",
                )
                db.add(candidate)
                db.flush()
                db.add(Evidence(
                    case_id=case.id, fact_id=candidate.id, document_id=document.id,
                    source_type="document", excerpt=maintenance.group(0)[:500], strength="medium",
                ))

            extraction = DocumentExtraction(
                document_id=document.id, extractor_version="local-text-3",
                raw_text=raw[:200000] if raw else None, structured_json=extracted,
                quality_flags=flags, completed_at=datetime.now(timezone.utc),
            )
            db.add(extraction)
            _audit(db, case.id, "DOCUMENT_UPLOADED", {
                "document_id": document.id, "sha256": digest,
                "storage_backend": storage.backend_name,
                "storage_persistent": storage.persistent,
                "processing_status": document.processing_status,
                "size_bytes": len(data),
            })
            db.commit()
            db.refresh(document)
            return document, extraction
        except Exception as exc:
            if isinstance(exc, StorageWriteError):
                created = exc.created
            db.rollback()
            if created:
                _compensate_new_object(db, storage, key)
            if isinstance(exc, (UnsafeDocumentUpload, DocumentUploadPersistenceError)):
                raise
            raise DocumentUploadPersistenceError("Document upload did not commit") from exc
