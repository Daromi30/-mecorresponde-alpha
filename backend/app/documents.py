from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any

from pypdf import PdfReader
from sqlalchemy.orm import Session

from .models import AuditEvent, Case, Document, DocumentExtraction, Evidence, Fact
from .storage import DocumentStorage, get_document_storage, object_key, validate_document_bytes


def _audit(db: Session, case_id: str, event_type: str, payload: dict[str, Any]) -> None:
    db.add(AuditEvent(case_id=case_id, event_type=event_type, payload_json=payload))


def save_upload(
    db: Session,
    case: Case,
    filename: str,
    content_type: str,
    data: bytes,
    *,
    storage: DocumentStorage | None = None,
):
    validate_document_bytes(filename, content_type, data)
    storage = storage or get_document_storage()

    digest = hashlib.sha256(data).hexdigest()
    key = object_key(case.id, digest)
    storage.put_bytes(key, data, content_type=content_type, sha256=digest)

    document = Document(
        case_id=case.id,
        storage_key=key,
        original_filename=filename,
        mime_type=content_type,
        sha256=digest,
    )
    db.add(document)
    db.flush()

    raw = ""
    pages = None
    flags: list[str] = []
    try:
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            pages = len(reader.pages)
            raw = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif content_type.startswith("text/") or filename.lower().endswith((".txt", ".csv")):
            raw = data.decode("utf-8", errors="replace")
        else:
            flags.append("NO_TEXT_EXTRACTOR_FOR_MIME")
        document.processing_status = "PROCESSED" if raw else "NEEDS_REVIEW"
        document.page_count = pages
    except Exception as exc:
        document.processing_status = "FAILED"
        flags.append(type(exc).__name__)

    extracted: dict[str, Any] = {}
    if raw:
        amounts = re.findall(r"(\d{1,5}[.,]\d{2})\s*(?:€|EUR)", raw, re.I)
        if amounts:
            extracted["possible_amounts"] = [float(value.replace(",", ".")) for value in amounts[:20]]

        maintenance = re.search(
            r"(?:mantenimiento|protecci[oó]n|servicio)[^\n€]{0,80}?(\d{1,3}[.,]\d{2})\s*(?:€|EUR)",
            raw,
            re.I,
        )
        if maintenance:
            price = float(maintenance.group(1).replace(",", "."))
            extracted["possible_addon_price"] = price
            candidate = Fact(
                case_id=case.id,
                key="electricity.addon.detected_price",
                value_json={"value": price},
                state="inferred",
                materiality="context",
                confidence=0.65,
                user_confirmed=False,
                created_by="system",
            )
            db.add(candidate)
            db.flush()
            db.add(Evidence(
                case_id=case.id,
                fact_id=candidate.id,
                document_id=document.id,
                source_type="document",
                excerpt=maintenance.group(0)[:500],
                strength="medium",
            ))

    extraction = DocumentExtraction(
        document_id=document.id,
        extractor_version="local-text-3",
        raw_text=raw[:200000] if raw else None,
        structured_json=extracted,
        quality_flags=flags,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(extraction)
    _audit(db, case.id, "DOCUMENT_UPLOADED", {
        "document_id": document.id,
        "storage_key": key,
        "sha256": digest,
        "storage_backend": storage.backend_name,
        "storage_persistent": storage.persistent,
        "extracted": extracted,
    })
    db.commit()
    db.refresh(document)
    return document, extraction
