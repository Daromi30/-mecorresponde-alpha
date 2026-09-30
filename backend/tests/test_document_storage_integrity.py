"""Provider-neutral document integrity tests with fictional bytes only."""

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.documents as documents_module
import app.case_lifecycle as case_lifecycle
from app.config import settings
from app.db import Base
from app.documents import DocumentUploadCompensationError, DocumentUploadPersistenceError, save_upload
from app.models import AuditEvent, Case, Document, DocumentExtraction, Evidence, Fact
from app.services_v2 import create_case
from app.storage import (
    LocalDocumentStorage, S3DocumentStorage, StorageIntegrityError,
    StorageConfigurationError, StorageWriteError, UnsafeDocumentUpload,
    object_key, read_verified_document,
    storage_status, validate_document_bytes,
)


class S3Error(Exception):
    def __init__(self, code):
        super().__init__("simulated S3 failure")
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.fail_head = False
        self.fail_get = False
        self.fail_put = False
        self.put_calls = 0
        self.delete_calls = 0

    def head_object(self, *, Bucket, Key):
        if self.fail_head:
            raise S3Error("AccessDenied")
        if Key not in self.objects:
            raise S3Error("404")
        return {"Metadata": self.objects[Key][1]}

    def get_object(self, *, Bucket, Key):
        if self.fail_get:
            raise S3Error("InternalError")
        data, metadata = self.objects[Key]
        return {"Body": io.BytesIO(data), "Metadata": metadata}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch):
        self.put_calls += 1
        assert IfNoneMatch == "*"
        if self.fail_put:
            raise S3Error("InternalError")
        if Key in self.objects:
            raise S3Error("PreconditionFailed")
        self.objects[Key] = (Body, Metadata)

    def delete_object(self, *, Bucket, Key):
        self.delete_calls += 1
        self.objects.pop(Key, None)


def fake_s3_storage():
    client = FakeS3()
    storage = object.__new__(S3DocumentStorage)
    storage.client = client
    storage.bucket = "fictional-bucket"
    storage.prefix = "fictional-prefix"
    return storage, client


def key_for(case_id, data):
    return object_key(case_id, hashlib.sha256(data).hexdigest())


def test_local_first_put_idempotence_and_immutable_conflict(tmp_path):
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional document"
    digest = hashlib.sha256(data).hexdigest()
    key = object_key("fictional-case", digest)
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created is True
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created is False
    assert storage.get_bytes(key) == data
    with pytest.raises(StorageIntegrityError):
        storage.put_bytes(key, b"different bytes", content_type="text/plain", sha256=digest)
    path = tmp_path / key
    path.write_bytes(b"tampered bytes")
    with pytest.raises(StorageIntegrityError):
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
    assert path.read_bytes() == b"tampered bytes"


def test_s3_first_put_idempotence_conflict_and_no_unconditional_overwrite():
    storage, client = fake_s3_storage()
    data = b"fictional object"
    digest = hashlib.sha256(data).hexdigest()
    key = object_key("fictional-case", digest)
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created is True
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created is False
    assert client.put_calls == 1
    client.objects[storage._key(key)] = (b"tampered", {"sha256": digest})
    with pytest.raises(StorageIntegrityError):
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
    assert client.put_calls == 1
    client.objects[storage._key(key)] = (data, {"sha256": "0" * 64})
    with pytest.raises(StorageIntegrityError):
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)


@pytest.mark.parametrize("failure", ["head", "get", "put"])
def test_s3_verification_or_put_failure_is_fail_closed(failure):
    storage, client = fake_s3_storage()
    data = b"fictional object"
    digest = hashlib.sha256(data).hexdigest()
    key = object_key("fictional-case", digest)
    if failure == "get":
        client.objects[storage._key(key)] = (data, {"sha256": digest})
    setattr(client, f"fail_{failure}", True)
    with pytest.raises((StorageIntegrityError, StorageWriteError)):
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
    if failure != "get":
        assert storage._key(key) not in client.objects


def test_s3_conditional_collision_rechecks_existing_without_overwrite():
    storage, client = fake_s3_storage()
    data = b"fictional object"
    digest = hashlib.sha256(data).hexdigest()
    key = object_key("fictional-case", digest)
    original_head = client.head_object
    calls = 0

    def racing_head(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise S3Error("404")
        return original_head(**kwargs)

    client.head_object = racing_head
    client.objects[storage._key(key)] = (data, {"sha256": digest})
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created is False
    assert client.put_calls == 1


def test_s3_post_write_verification_failure_compensates_new_object(db):
    case = create_case(db, "Fictional electricity dispute")
    storage, client = fake_s3_storage()
    data = b"fictional text"
    key = key_for(case.id, data)
    client.fail_get = True
    with pytest.raises(DocumentUploadPersistenceError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert storage._key(key) not in client.objects
    assert client.delete_calls == 1
    assert db.scalars(select(Document)).all() == []


def test_simultaneous_same_case_uploads_share_one_document(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fictional-concurrency.sqlite'}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        case = Case(id="fictional-case", raw_intake="fictional")
        session.add(case)
        session.commit()
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    barrier = Barrier(2)
    data = b"fictional concurrent bytes"

    def upload():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            document, _ = save_upload(
                session, Case(id="fictional-case"), "x.txt", "text/plain", data,
                storage=storage,
            )
            return document.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: upload(), range(2)))
    assert ids[0] == ids[1]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
    assert storage.get_bytes(key_for("fictional-case", data)) == data
    engine.dispose()


@pytest.mark.parametrize("filename,mime,data,canonical", [
    ("x.pdf", "application/pdf", b"%PDF-fictional", "application/pdf"),
    ("x.jpg", "image/jpeg", b"\xff\xd8\xfffictional", "image/jpeg"),
    ("x.png", "image/png", b"\x89PNG\r\n\x1a\nfictional", "image/png"),
    ("x.webp", "image/webp", b"RIFFxxxxWEBPfictional", "image/webp"),
    ("x.txt", "application/octet-stream", b"fictional text", "text/plain"),
    ("x.csv", "text/csv", b"one,two\n1,2", "text/csv"),
])
def test_validated_mime_is_canonical(filename, mime, data, canonical):
    assert validate_document_bytes(filename, mime, data) == canonical


@pytest.mark.parametrize("filename,mime,data", [
    ("x.png", "application/pdf", b"\x89PNG\r\n\x1a\nfictional"),
    ("x.pdf", "image/png", b"%PDF-fictional"),
    ("x.txt", "text/plain", b"\x00binary"),
    ("x.txt", "text/plain", b"%PDF-fictional"),
    ("x.csv", "text/csv", b"\xff\xfebinary"),
])
def test_mime_signature_or_extension_conflict_is_rejected(filename, mime, data):
    with pytest.raises(UnsafeDocumentUpload):
        validate_document_bytes(filename, mime, data)


def test_saved_mime_and_upload_audit_are_minimal(tmp_path, db):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    raw = b"mantenimiento 8,99 EUR private fictional text"
    document, extraction = save_upload(db, case, "x.txt", "application/octet-stream", raw, storage=storage)
    assert document.mime_type == "text/plain"
    assert extraction.structured_json["possible_addon_price"] == 8.99
    event = db.scalar(select(AuditEvent).where(AuditEvent.case_id == case.id, AuditEvent.event_type == "DOCUMENT_UPLOADED"))
    assert set(event.payload_json) == {
        "document_id", "sha256", "storage_backend", "storage_persistent",
        "processing_status", "size_bytes",
    }
    assert "private fictional text" not in str(event.payload_json)
    assert "8.99" not in str(event.payload_json)
    assert document.storage_key not in str(event.payload_json)


def test_verified_read_accepts_valid_bytes_and_rejects_tampering(tmp_path, db):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional text"
    document, _ = save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert read_verified_document(storage, document) == data
    (tmp_path / document.storage_key).write_bytes(b"tampered")
    with pytest.raises(StorageIntegrityError):
        read_verified_document(storage, document)


def test_new_object_is_compensated_after_commit_failure(tmp_path, db, monkeypatch):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional text"
    key = key_for(case.id, data)
    def failed_commit():
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(db, "commit", failed_commit)
    with pytest.raises(DocumentUploadPersistenceError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert not (tmp_path / key).exists()
    assert db.scalars(select(Document)).all() == []


@pytest.mark.parametrize("failure", ["document_flush", "fact_flush", "audit"])
def test_new_object_is_compensated_for_each_sql_pipeline_failure(tmp_path, db, monkeypatch, failure):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"mantenimiento 8,99 EUR fictional text"
    key = key_for(case.id, data)
    if failure == "audit":
        def failed_audit(*args):
            raise RuntimeError("simulated audit failure")
        monkeypatch.setattr(documents_module, "_audit", failed_audit)
    else:
        real_flush = db.flush
        calls = 0
        def selective_flush(*args, **kwargs):
            nonlocal calls
            calls += 1
            if (failure == "document_flush" and calls == 1) or (failure == "fact_flush" and calls == 2):
                raise RuntimeError("simulated SQL flush failure")
            return real_flush(*args, **kwargs)
        monkeypatch.setattr(db, "flush", selective_flush)
    with pytest.raises(DocumentUploadPersistenceError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert not (tmp_path / key).exists()
    assert db.scalars(select(Document)).all() == []
    assert db.scalars(select(Evidence)).all() == []


def test_repeat_upload_is_idempotent_at_object_and_document_level(tmp_path, db):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional repeat bytes"
    first_document, first_extraction = save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    second_document, second_extraction = save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert second_document.id == first_document.id
    assert second_extraction.id == first_extraction.id
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "DOCUMENT_UPLOADED")) == 1


def test_preexisting_object_is_not_deleted_after_database_failure(tmp_path, db, monkeypatch):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional text"
    digest = hashlib.sha256(data).hexdigest()
    key = object_key(case.id, digest)
    assert storage.put_bytes(key, data, content_type="text/plain", sha256=digest).created
    def failed_commit():
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(db, "commit", failed_commit)
    with pytest.raises(DocumentUploadPersistenceError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert storage.get_bytes(key) == data
    assert db.scalars(select(Document)).all() == []


def test_compensation_preserves_object_if_database_commit_was_acknowledged_late(tmp_path, db, monkeypatch):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional text"
    key = key_for(case.id, data)
    real_commit = db.commit
    def commit_then_lose_ack():
        real_commit()
        raise RuntimeError("simulated lost acknowledgement")
    monkeypatch.setattr(db, "commit", commit_then_lose_ack)
    with pytest.raises(DocumentUploadPersistenceError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert storage.get_bytes(key) == data
    assert db.scalars(select(Document).where(Document.storage_key == key)).one()


def test_failed_compensation_is_explicit_and_does_not_log_content(tmp_path, db, monkeypatch, caplog):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional private text"
    def failed_commit():
        raise RuntimeError("simulated database failure")
    def failed_delete(key):
        raise RuntimeError("simulated deletion failure")
    monkeypatch.setattr(db, "commit", failed_commit)
    monkeypatch.setattr(storage, "delete_bytes", failed_delete)
    with pytest.raises(DocumentUploadCompensationError):
        save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    assert "fictional private text" not in caplog.text
    assert "DOCUMENT_UPLOAD_COMPENSATION_FAILED" in caplog.text


def test_extractor_failure_retains_failed_document_consistently(tmp_path, db, monkeypatch):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"%PDF-fictional malformed test bytes"
    def failed_reader(*args):
        raise ValueError("fictional extractor failure")
    monkeypatch.setattr(documents_module, "PdfReader", failed_reader)
    document, extraction = save_upload(db, case, "x.pdf", "application/pdf", data, storage=storage)
    assert document.processing_status == "FAILED"
    assert extraction.quality_flags == ["ValueError"]
    assert extraction.raw_text is None
    assert extraction.structured_json == {}
    assert storage.get_bytes(document.storage_key) == data
    assert db.scalars(select(Evidence).where(Evidence.document_id == document.id)).all() == []
    assert db.scalars(select(Fact).where(Fact.case_id == case.id, Fact.created_by == "system")).all() == []


def test_render_local_flag_does_not_claim_durability(monkeypatch):
    monkeypatch.setattr(settings, "render", True)
    status = storage_status(LocalDocumentStorage("fictional-local-root", persistent=True))
    assert status.backend == "local"
    assert status.persistent is False
    assert status.uploads_allowed is False


@pytest.mark.parametrize("field,value", [
    ("s3_bucket", ""),
    ("s3_bucket", "bucket with spaces"),
    ("s3_region", ""),
    ("s3_access_key_id", ""),
    ("s3_secret_access_key", ""),
    ("s3_prefix", "../escape"),
    ("s3_endpoint_url", "http://insecure.example.test"),
    ("s3_endpoint_url", "https://user:secret@storage.example.test"),
    ("s3_endpoint_url", "https://[broken-ipv6"),
    ("s3_endpoint_url", ""),
])
def test_invalid_s3_configuration_fails_before_client_creation(monkeypatch, field, value):
    monkeypatch.setattr(settings, "s3_bucket", "fictional-bucket")
    monkeypatch.setattr(settings, "s3_region", "eu-test-1")
    monkeypatch.setattr(settings, "s3_access_key_id", "fictional-access")
    monkeypatch.setattr(settings, "s3_secret_access_key", "fictional-secret")
    monkeypatch.setattr(settings, "s3_prefix", "fictional-prefix")
    monkeypatch.setattr(settings, "s3_endpoint_url", "https://storage.example.test")
    monkeypatch.setattr(settings, field, value)
    if field == "s3_endpoint_url" and value == "":
        monkeypatch.setattr(settings, "s3_region", "auto")
    with pytest.raises(StorageConfigurationError) as captured:
        S3DocumentStorage()
    assert "fictional-secret" not in str(captured.value)


def test_sql_flush_failure_does_not_delete_case_document_bytes(tmp_path, db, monkeypatch):
    case = create_case(db, "Fictional electricity dispute")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    data = b"fictional text"
    document, _ = save_upload(db, case, "x.txt", "text/plain", data, storage=storage)
    monkeypatch.setattr(case_lifecycle, "get_document_storage", lambda: storage)

    def failed_flush():
        raise RuntimeError("simulated SQL flush failure")

    monkeypatch.setattr(db, "flush", failed_flush)
    with pytest.raises(RuntimeError, match="simulated SQL flush failure"):
        case_lifecycle.delete_case_and_data(db, case)
    db.rollback()
    assert storage.get_bytes(document.storage_key) == data
    assert db.get(Document, document.id) is not None
