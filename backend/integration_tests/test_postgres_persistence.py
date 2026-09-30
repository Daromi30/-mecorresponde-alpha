from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, SessionLocal, engine
from app.document_storage_reconciliation import (
    COMPLETE, add_delete_tombstones, authorize_put_after_missing_probe,
    create_put_intent, reconcile_document_storage_operations,
)
from app.documents import save_upload
from app.main import persistence_health
from app.models import Case, Decision, Document, DocumentStorageOperation, Evidence, Fact
from app.services_v2 import create_case, diagnose, seed_legal, upsert_fact
from app.storage import LocalDocumentStorage, ObjectProbe, object_key
import hashlib


def test_case_survives_new_postgres_session():
    # Disposable CI database: exercise the same SQLAlchemy models against PostgreSQL.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_legal(db)
        db.commit()
        case = create_case(db, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
        case_id = case.id
        upsert_fact(db, case, "electricity.supply_end_date", "2026-06-03", state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.identity", "Protección Hogar", state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.ever_contracted", True, state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.contracted_with_supply", True, state="confirmed", user_confirmed=True)
        upsert_fact(db, case, "electricity.addon.keep_requested", False, state="confirmed", user_confirmed=True)
        upsert_fact(
            db,
            case,
            "electricity.addon.charges",
            [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                }
            ],
            state="confirmed",
            user_confirmed=True,
        )
        result, decision, _ = diagnose(db, case)
        assert result.viability == "HIGH"
        assert result.claimable_amount == 8.99
        decision_id = decision.id

    # A fresh database session must recover the expediente and its audit-bearing records.
    with SessionLocal() as db:
        recovered = db.get(Case, case_id)
        assert recovered is not None
        assert recovered.status == "DIAGNOSED"
        assert recovered.current_decision_id == decision_id

        facts = db.scalars(select(Fact).where(Fact.case_id == case_id)).all()
        evidence = db.scalars(select(Evidence).where(Evidence.case_id == case_id)).all()
        decisions = db.scalars(select(Decision).where(Decision.case_id == case_id)).all()

        assert len(facts) >= 6
        assert len(evidence) >= 6
        assert len(decisions) >= 1
        assert decisions[-1].claimable_amount == 8.99

    gate = persistence_health()
    assert gate == {"status": "ok", "database": "postgresql", "persistent": True}


def test_postgres_key_lock_serializes_same_document_upload(tmp_path):
    # Disposable CI PostgreSQL plus fictional local bytes; no provider or LIVE data.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        case = Case(raw_intake="fictional concurrent document")
        db.add(case)
        db.commit()
        case_id = case.id
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional simultaneous document"
    barrier = Barrier(2)

    def upload():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            document, _ = save_upload(
                db, Case(id=case_id), "fictional.txt", "text/plain", data,
                storage=storage,
            )
            return document.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: upload(), range(2)))
    assert ids[0] == ids[1]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document).where(Document.case_id == case_id)) == 1


def test_postgres_durable_put_and_tombstone_recover_with_new_sessions(tmp_path):
    Base.metadata.create_all(bind=engine)
    storage = LocalDocumentStorage(tmp_path / "objects", persistent=True)
    data = b"fictional postgres crash recovery"
    digest = hashlib.sha256(data).hexdigest()
    with SessionLocal() as db:
        case = Case(raw_intake="fictional postgres recovery")
        db.add(case)
        db.commit()
        key = object_key(case.id, digest)
        put = create_put_intent(db, key=key, sha256=digest, backend="local", case_id=case.id)
        authorize_put_after_missing_probe(db, put)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        put_id = put.id
    with SessionLocal() as restarted:
        assert restarted.get(DocumentStorageOperation, put_id).state == "PENDING"
        reconcile_document_storage_operations(restarted, storage=storage)
        restarted.expire_all()
        assert restarted.get(DocumentStorageOperation, put_id).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        restarted.add(document)
        restarted.commit()
        ids = add_delete_tombstones(restarted, [document], backend="local")
        restarted.delete(document)
        restarted.commit()
    with SessionLocal() as restarted_again:
        assert restarted_again.get(DocumentStorageOperation, ids[0]).state == "CLEANUP"
        reconcile_document_storage_operations(restarted_again, storage=storage)
        restarted_again.expire_all()
        assert restarted_again.get(DocumentStorageOperation, ids[0]).state == COMPLETE
        assert storage.probe_object(key, digest) == ObjectProbe.MISSING


def test_postgres_put_intent_cannot_commit_flushed_business_change():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        case = Case(raw_intake="fictional intent isolation")
        db.add(case)
        db.commit()
        case_id = case.id
        case.title = "fictional uncommitted title"
        db.flush()
        digest = hashlib.sha256(b"fictional intent").hexdigest()
        key = object_key(case_id, digest)
        operation = create_put_intent(db, key=key, sha256=digest, backend="local", case_id=case_id)
        with SessionLocal() as check:
            assert check.get(DocumentStorageOperation, operation.id).state == "PENDING"
            assert check.get(Case, case_id).title is None
        db.rollback()
    with SessionLocal() as check:
        assert check.get(Case, case_id).title is None
        assert check.get(DocumentStorageOperation, operation.id).state == "PENDING"


def test_postgres_upload_uses_at_most_two_pooled_connections(tmp_path):
    Base.metadata.create_all(bind=engine)
    limited_engine = create_engine(engine.url, pool_size=2, max_overflow=0, pool_timeout=3)
    LimitedSession = sessionmaker(bind=limited_engine, autoflush=False, expire_on_commit=False)
    try:
        with LimitedSession() as db:
            case = Case(raw_intake="fictional bounded-pool upload")
            db.add(case)
            db.commit()
            case = db.get(Case, case.id)
            storage = LocalDocumentStorage(tmp_path / "bounded-pool", persistent=True)
            document, _ = save_upload(
                db, case, "fictional.txt", "text/plain", b"fictional bounded-pool bytes",
                storage=storage,
            )
            assert document.case_id == case.id
    finally:
        limited_engine.dispose()


def test_postgres_two_reconcilers_compete_safely_for_same_tombstone(tmp_path):
    Base.metadata.create_all(bind=engine)
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
    data = b"fictional postgres competing reconcilers"
    digest = hashlib.sha256(data).hexdigest()
    with SessionLocal() as db:
        case = Case(raw_intake="fictional postgres claim")
        db.add(case)
        db.commit()
        key = object_key(case.id, digest)
        storage.put_bytes(key, data, content_type="text/plain", sha256=digest)
        document = Document(case_id=case.id, storage_key=key, sha256=digest,
                            original_filename="fictional.txt", mime_type="text/plain")
        db.add(document)
        db.commit()
        ids = add_delete_tombstones(db, [document], backend="local")
        db.delete(document)
        db.commit()
    barrier = Barrier(2)
    def worker():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            return reconcile_document_storage_operations(db, storage=storage, operation_ids=ids)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(item["completed"] for item in results) == 1
    assert storage.calls == 1
    with SessionLocal() as db:
        assert db.get(DocumentStorageOperation, ids[0]).state == COMPLETE
