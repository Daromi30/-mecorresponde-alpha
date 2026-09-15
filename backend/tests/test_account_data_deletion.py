from pathlib import Path

from sqlalchemy import func, select

import app.account_lifecycle as lifecycle
from app.auth_models import User, UserSession
from app.models import AIRun, AuditEvent, Case, Document, DocumentExtraction
from app.storage import LocalDocumentStorage


PASSWORD = "strong-password-for-deletion"


class RecordingStorage:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_bytes(self, key: str) -> None:
        self.deleted.append(key)


def register_and_claim_case(client):
    registered = client.post(
        "/api/auth/register",
        json={"email": "delete-me@example.com", "password": PASSWORD},
    )
    assert registered.status_code == 201
    user_id = registered.json()["user"]["id"]

    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200
    return user_id, case_id


def test_account_deletion_requires_password_and_exact_confirmation(client, db):
    user_id, case_id = register_and_claim_case(client)

    bad_confirmation = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirmation": "yes"},
    )
    assert bad_confirmation.status_code == 422

    wrong_password = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": "wrong-password-long-enough", "confirmation": "DELETE"},
    )
    assert wrong_password.status_code == 401
    db.expire_all()
    assert db.get(User, user_id) is not None
    assert db.get(Case, case_id) is not None


def test_account_deletion_removes_owned_cases_sessions_audit_ai_and_documents(
    client, db, monkeypatch
):
    user_id, case_id = register_and_claim_case(client)
    document = Document(
        case_id=case_id,
        storage_key=f"originals/{case_id}/aa/test-object",
        original_filename="factura.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        processing_status="EXTRACTED",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentExtraction(
            document_id=document.id,
            extractor_version="test",
            raw_text="synthetic",
            structured_json={"amount": 10},
            quality_flags=[],
        )
    )
    db.commit()

    storage = RecordingStorage()
    monkeypatch.setattr(lifecycle, "get_document_storage", lambda: storage)

    deleted = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirmation": "DELETE"},
    )
    assert deleted.status_code == 200
    body = deleted.json()
    assert body == {"status": "deleted", "cases_deleted": 1, "documents_deleted": 1}
    assert storage.deleted == [f"originals/{case_id}/aa/test-object"]

    assert client.get("/api/auth/me").status_code == 401
    db.expire_all()
    assert db.get(User, user_id) is None
    assert db.get(Case, case_id) is None
    assert db.scalar(select(func.count()).select_from(UserSession)) == 0
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert db.scalar(select(func.count()).select_from(DocumentExtraction)) == 0
    assert db.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id)
    ) == 0
    assert db.scalar(
        select(func.count()).select_from(AIRun).where(AIRun.case_id == case_id)
    ) == 0


def test_account_deletion_fails_closed_when_document_storage_delete_fails(
    client, db, monkeypatch
):
    user_id, case_id = register_and_claim_case(client)
    db.add(
        Document(
            case_id=case_id,
            storage_key="originals/failure/object",
            original_filename="evidence.pdf",
            mime_type="application/pdf",
            sha256="b" * 64,
        )
    )
    db.commit()

    class BrokenStorage:
        def delete_bytes(self, key: str) -> None:
            raise RuntimeError("synthetic storage failure")

    monkeypatch.setattr(lifecycle, "get_document_storage", lambda: BrokenStorage())
    response = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirmation": "DELETE"},
    )
    assert response.status_code == 503
    db.expire_all()
    assert db.get(User, user_id) is not None
    assert db.get(Case, case_id) is not None


def test_local_document_storage_delete_is_idempotent(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    key = "originals/case/aa/file"
    storage.put_bytes(key, b"hello", content_type="text/plain", sha256="0" * 64)
    assert storage.get_bytes(key) == b"hello"
    storage.delete_bytes(key)
    storage.delete_bytes(key)
    assert not (tmp_path / key).exists()
