from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .document_storage_lock import document_key_lock
from .document_storage_reconciliation import (
    authorize_put_after_missing_probe, complete_put_with_document,
    create_put_intent, reconcile_document_storage_operations,
)
from .models import AuditEvent, Case, Document, DocumentExtraction, Evidence, Fact
from .storage import (
    DocumentStorage, ObjectProbe, UnsafeDocumentUpload,
    get_document_storage, object_key, read_verified_document, validate_document_bytes,
)


class DocumentUploadPersistenceError(RuntimeError):
    pass


class DocumentUploadCompensationError(DocumentUploadPersistenceError):
    pass


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
    operation_id: str | None = None
    try:
        with document_key_lock(db, key):
            existing = db.scalar(select(Document).where(Document.case_id == case.id, Document.storage_key == key))
            if existing is not None:
                read_verified_document(storage, existing)
                extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == existing.id))
                if extraction is None:
                    raise DocumentUploadPersistenceError("Existing document has no extraction record")
                return existing, extraction

            _enforce_alpha_document_quota(db, case.id)
            operation = create_put_intent(
                db, key=key, sha256=digest, backend=storage.backend_name, case_id=case.id,
            )
            operation_id = operation.id
            preflight = storage.probe_object(key, digest)
            if preflight == ObjectProbe.MISSING:
                authorize_put_after_missing_probe(db, operation)
                storage.put_bytes(key, data, content_type=canonical_mime, sha256=digest)
            elif preflight == ObjectProbe.PRESENT_CONFLICTING:
                raise DocumentUploadPersistenceError("Existing document object conflicts with expected hash")
            elif preflight == ObjectProbe.UNKNOWN:
                raise DocumentUploadPersistenceError("Document object state could not be verified")
            elif preflight != ObjectProbe.PRESENT_AND_VALID:
                raise DocumentUploadPersistenceError("Unsupported document object probe result")
            # PRESENT_AND_VALID predates this attempt; do not overwrite or
            # authorize cleanup if the subsequent SQL transaction fails.
            if db.scalar(select(Case.id).where(Case.id == case.id).with_for_update()) is None:
                raise DocumentUploadPersistenceError("Case no longer exists")
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
            complete_put_with_document(operation, document)
            db.commit()
            db.refresh(document)
            return document, extraction
    except Exception as exc:
        db.rollback()
        if operation_id is not None:
            outcome = reconcile_document_storage_operations(
                db, storage=storage, operation_ids=[operation_id], limit=1,
            )
            if outcome["retry"] or outcome["blocked"]:
                raise DocumentUploadCompensationError("Document upload failed; durable reconciliation is pending") from None
        if isinstance(exc, (UnsafeDocumentUpload, DocumentUploadPersistenceError)):
            raise
        raise DocumentUploadPersistenceError("Document upload did not commit") from exc
