"""Durable reconciliation tests: only fictional bytes and temporary paths."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
import app.case_lifecycle as case_lifecycle
from app.document_storage_reconciliation import (
    BLOCKED, CLEANUP, COMPLETE, PENDING, RETRY, _transition,
    add_delete_tombstones, authorize_put_after_missing_probe, create_put_intent,
    document_storage_operation_status, reconcile_document_storage_operations,
)
from app.documents import DocumentUploadPersistenceError, save_upload
from app.models import Case, Document, DocumentStorageOperation
from app.storage import LocalDocumentStorage, ObjectProbe, StorageWriteError, object_key


def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fictional-operations.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def case_and_key(db, data=b"fictional document bytes"):
    case = Case(raw_intake="fictional case")
    db.add(case)
    db.commit()
    digest = hashlib.sha256(data).hexdigest()
    return case, object_key(case.id, digest), digest


def pending_put(db, storage, case, key, digest):
    operation = create_put_intent(db, key=key, sha256=digest, backend=storage.backend_name, case_id=case.id)
    authorize_put_after_missing_probe(db, operation)
    return operation


def test_put_intent_is_committed_before_any_external_mutation(tmp_path):
    SessionLocal = database(tmp_path)
    data = b"fictional uploaded bytes"
    class ObservingStorage(LocalDocumentStorage):
        def put_bytes(self, key, data, *, content_type, sha256):
            with SessionLocal() as check:
                operation = check.scalar(select(DocumentStorageOperation).where(DocumentStorageOperation.storage_key == key))
                assert operation.state == PENDING
                assert operation.cleanup_allowed is True
            return super().put_bytes(key, data, content_type=content_type, sha256=sha256)
    storage = ObservingStorage(tmp_path / "objects", persistent=True)
    with SessionLocal() as db:
        case, _, _ = case_and_key(db, data)
        document, _ = save_upload(db, case, "fictional.txt", "text/plain", data, storage=storage)
        operation = db.scalar(select(DocumentStorageOperation))
        assert operation.state == COMPLETE
        assert operation.document_id == document.id
        assert operation.attempt_count == 0


@pytest.mark.parametrize("object_written", [True, False])
def test_crash_after_durable_put_is_recovered_in_new_session(tmp_path, object_written):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional orphan"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        operation_id = operation.id
        if object_written:
            storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        # Simulates process crash: no Document commit and no in-process cleanup.
    with SessionLocal() as restarted:
        result = reconcile_document_storage_operations(restarted, storage=storage)
        assert result == {"attempted": 1, "completed": 1, "retry": 0, "blocked": 0}
        assert restarted.get(DocumentStorageOperation, operation_id).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING
        assert restarted.scalar(select(func.count()).select_from(Document)) == 0


def test_ambiguous_put_created_object_is_reconciled_without_materializing_document(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional ambiguous put"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        # No ACK was received; durable may-create marker survives this process.
        operation_id = operation.id
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        assert restarted.get(DocumentStorageOperation, operation_id).state == COMPLETE
        assert restarted.scalar(select(func.count()).select_from(Document)) == 0
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


@pytest.mark.parametrize("write_before_timeout", [True, False])
def test_upload_ambiguous_put_error_uses_durable_intent(tmp_path, write_before_timeout):
    SessionLocal = database(tmp_path)
    class AmbiguousStorage(LocalDocumentStorage):
        def put_bytes(self, key, data, *, content_type, sha256):
            if write_before_timeout:
                super().put_bytes(key, data, content_type=content_type, sha256=sha256)
            raise StorageWriteError("fictional lost PUT acknowledgement", created=False)
    storage = AmbiguousStorage(tmp_path / "objects", persistent=True)
    data = b"fictional lost acknowledgement"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        with pytest.raises(DocumentUploadPersistenceError):
            save_upload(db, case, "fictional.txt", "text/plain", data, storage=storage)
    with SessionLocal() as restarted:
        operation = restarted.scalar(select(DocumentStorageOperation))
        assert operation.cleanup_allowed is True
        assert operation.state == COMPLETE
        assert restarted.scalar(select(func.count()).select_from(Document)) == 0
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


def test_preexisting_object_is_never_cleaned_by_failed_put_intent(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional preexisting object"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        operation = create_put_intent(db, key=key, sha256=digest, backend="local", case_id=case.id)
        operation_id = operation.id
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        assert restarted.get(DocumentStorageOperation, operation_id).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID


def test_conflicting_object_blocks_without_overwrite_or_delete(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    with SessionLocal() as db:
        case, key, digest = case_and_key(db)
        operation = pending_put(db, storage, case, key, digest)
        path = storage._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fictional conflicting bytes")
        operation_id = operation.id
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        assert restarted.get(DocumentStorageOperation, operation_id).state == BLOCKED
        assert path.read_bytes() == b"fictional conflicting bytes"


def test_delete_tombstone_survives_commit_and_restart_before_physical_delete(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional delete"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        ids = add_delete_tombstones(db, [document], backend="local")
        db.delete(document)
        db.commit()
        assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        assert restarted.get(DocumentStorageOperation, ids[0]).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


def test_case_delete_never_touches_object_before_sql_commit(tmp_path, monkeypatch):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional commit sequence"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        real_commit = db.commit
        def assert_precommit():
            assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID
            assert db.scalar(select(func.count()).select_from(DocumentStorageOperation)) == 1
            return real_commit()
        monkeypatch.setattr(db, "commit", assert_precommit)
        monkeypatch.setattr(case_lifecycle, "get_document_storage", lambda: storage)
        result = case_lifecycle.delete_case_and_data(db, case)
        assert result.storage_cleanup_pending is False
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


def test_failed_sql_delete_commit_leaves_document_and_object_intact(tmp_path, monkeypatch):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional failed SQL commit"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        case_id, document_id = case.id, document.id
        monkeypatch.setattr(case_lifecycle, "get_document_storage", lambda: storage)
        def fail_commit():
            raise RuntimeError("fictional SQL failure")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="fictional SQL failure"):
            case_lifecycle.delete_case_and_data(db, case)
    with SessionLocal() as restarted:
        assert restarted.get(Case, case_id) is not None
        assert restarted.get(Document, document_id) is not None
        assert restarted.scalar(select(func.count()).select_from(DocumentStorageOperation)) == 0
        assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID


def test_partial_multi_delete_recovers_after_restart(tmp_path, monkeypatch):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    with SessionLocal() as db:
        case, _, _ = case_and_key(db)
        keys = []
        for index in range(3):
            data = f"fictional object {index}".encode()
            digest = hashlib.sha256(data).hexdigest()
            key = object_key(case.id, digest)
            storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
            db.add(Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename=f"fictional-{index}.txt", mime_type="text/plain"))
            keys.append((key, digest))
        db.commit()
        real_delete = storage.delete_bytes
        failed = False
        def partial(key):
            nonlocal failed
            if key == keys[1][0] and not failed:
                failed = True
                raise TimeoutError("fictional timeout")
            return real_delete(key)
        monkeypatch.setattr(storage, "delete_bytes", partial)
        monkeypatch.setattr(case_lifecycle, "get_document_storage", lambda: storage)
        result = case_lifecycle.delete_case_and_data(db, case)
        assert result.documents_deleted == 3
        assert result.storage_cleanup_pending is True
        assert db.get(Case, case.id) is None
        assert storage.probe_object(*keys[0]) == ObjectProbe.MISSING
        assert storage.probe_object(*keys[1]) == ObjectProbe.PRESENT_AND_VALID
    with SessionLocal() as restarted:
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        reconcile_document_storage_operations(restarted, storage=storage, at=later)
        assert all(storage.probe_object(*item) == ObjectProbe.MISSING for item in keys)
        assert restarted.scalar(select(func.count()).select_from(DocumentStorageOperation).where(
            DocumentStorageOperation.state == COMPLETE)) == 3


def test_upload_and_reconciler_same_key_do_not_destroy_committed_document(tmp_path):
    SessionLocal = database(tmp_path)
    entered = Event()
    release = Event()
    class PausingStorage(LocalDocumentStorage):
        def put_bytes(self, key, data, *, content_type, sha256):
            entered.set()
            assert release.wait(timeout=10)
            return super().put_bytes(key, data, content_type=content_type, sha256=sha256)
    storage = PausingStorage(tmp_path / "objects", persistent=True)
    data = b"fictional concurrent upload"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        case_id = case.id
    def upload():
        with SessionLocal() as db:
            save_upload(db, Case(id=case_id), "fictional.txt", "text/plain", data, storage=storage)
    def reconcile():
        with SessionLocal() as db:
            return reconcile_document_storage_operations(db, storage=storage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        upload_future = pool.submit(upload)
        assert entered.wait(timeout=10)
        reconcile_future = pool.submit(reconcile)
        release.set()
        upload_future.result(timeout=20)
        reconcile_future.result(timeout=20)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document).where(Document.storage_key == key)) == 1
        assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID


def test_transient_delete_error_retries_without_hot_loop(tmp_path, monkeypatch):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional retry"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        operation_id = operation.id
    real_delete = storage.delete_bytes
    failures = 1
    def once(key):
        nonlocal failures
        if failures:
            failures -= 1
            raise TimeoutError("fictional transient failure")
        return real_delete(key)
    monkeypatch.setattr(storage, "delete_bytes", once)
    now = datetime.now(timezone.utc)
    with SessionLocal() as restarted:
        assert reconcile_document_storage_operations(restarted, storage=storage, at=now)["retry"] == 1
        row = restarted.get(DocumentStorageOperation, operation_id)
        assert row.state == RETRY and row.attempt_count == 1
        assert row.last_error_type == "TimeoutError"
        assert reconcile_document_storage_operations(restarted, storage=storage, at=now)["attempted"] == 0
        later = now + timedelta(hours=2)
        assert reconcile_document_storage_operations(restarted, storage=storage, at=later)["completed"] == 1
        restarted.expire_all()
        assert restarted.get(DocumentStorageOperation, operation_id).attempt_count == 2
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


def test_delete_lost_ack_retries_and_confirms_missing_on_restart(tmp_path, monkeypatch):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional delete ACK lost"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        operation_id = operation.id
    real_delete = storage.delete_bytes
    def delete_then_timeout(key):
        real_delete(key)
        raise TimeoutError("fictional delete ACK lost")
    monkeypatch.setattr(storage, "delete_bytes", delete_then_timeout)
    now = datetime.now(timezone.utc)
    with SessionLocal() as restarted:
        assert reconcile_document_storage_operations(restarted, storage=storage, at=now)["retry"] == 1
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING
        later = now + timedelta(hours=2)
        assert reconcile_document_storage_operations(restarted, storage=storage, at=later)["completed"] == 1
        restarted.expire_all()
        assert restarted.get(DocumentStorageOperation, operation_id).state == COMPLETE


def test_committed_reference_preserves_valid_object_and_missing_reference_blocks(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional referenced object"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        ids = add_delete_tombstones(db, [document], backend="local")
        db.commit()  # stale tombstone; Document remains committed
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        assert restarted.get(DocumentStorageOperation, ids[0]).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.PRESENT_AND_VALID
        second = add_delete_tombstones(restarted, [document], backend="local")
        restarted.commit()
        storage.delete_bytes(key)
        reconcile_document_storage_operations(restarted, storage=storage)
        restarted.expire_all()
        assert restarted.get(DocumentStorageOperation, second[0]).state == BLOCKED
        assert restarted.get(Document, document.id) is not None


def test_duplicate_tombstones_are_idempotent_and_status_has_no_keys(tmp_path):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional duplicate"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        first = add_delete_tombstones(db, [document], backend="local")
        second = add_delete_tombstones(db, [document], backend="local")
        db.delete(document)
        db.commit()
    with SessionLocal() as restarted:
        result = reconcile_document_storage_operations(restarted, storage=storage)
        assert result["completed"] == 2
        assert restarted.get(DocumentStorageOperation, first[0]).state == COMPLETE
        assert restarted.get(DocumentStorageOperation, second[0]).state == COMPLETE
        status = document_storage_operation_status(restarted)
        assert status["completed_recent"] == 2
        assert key not in str(status)


def test_two_reconcilers_claim_same_operation_once(tmp_path):
    SessionLocal = database(tmp_path)
    class CountingStorage(LocalDocumentStorage):
        def __init__(self, root):
            super().__init__(root, persistent=True)
            self.calls = 0
            self.guard = Lock()
        def delete_bytes(self, key):
            with self.guard:
                self.calls += 1
            return super().delete_bytes(key)
    storage = CountingStorage(tmp_path / "objects")
    data = b"fictional concurrent cleanup"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        operation_id = operation.id
    barrier = Barrier(2)
    def worker():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            return reconcile_document_storage_operations(db, storage=storage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(result["completed"] for result in results) == 1
    assert storage.calls == 1
    with SessionLocal() as db:
        assert db.get(DocumentStorageOperation, operation_id).state == COMPLETE


def test_invalid_state_transition_fails_closed(tmp_path):
    SessionLocal = database(tmp_path)
    with SessionLocal() as db:
        case, key, digest = case_and_key(db)
        operation = create_put_intent(db, key=key, sha256=digest, backend="local", case_id=case.id)
        _transition(operation, COMPLETE, at=datetime.now(timezone.utc))
        with pytest.raises(RuntimeError, match="Invalid document storage operation transition"):
            _transition(operation, CLEANUP, at=datetime.now(timezone.utc))


def test_no_sensitive_content_in_operation_row_or_log(tmp_path, caplog):
    SessionLocal = database(tmp_path)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional-secret-document-content"
    with SessionLocal() as db:
        case, key, digest = case_and_key(db, data)
        operation = pending_put(db, storage, case, key, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        operation_id = operation.id
    with SessionLocal() as restarted:
        reconcile_document_storage_operations(restarted, storage=storage)
        row = restarted.get(DocumentStorageOperation, operation_id)
        assert not any("filename" in column.name or "raw_text" in column.name for column in row.__table__.columns)
        serialized = " ".join(str(getattr(row, column.name)) for column in row.__table__.columns)
        assert "fictional-secret-document-content" not in serialized + caplog.text
        assert key not in caplog.text
