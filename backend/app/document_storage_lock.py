"""Serialize mutations for one content-addressed key across workers."""

import hashlib
import threading
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

_local_key_locks: dict[str, threading.Lock] = {}
_local_key_locks_guard = threading.Lock()


@contextmanager
def document_key_lock(db: Session, key: str):
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        with bind.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
            try:
                yield
            finally:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
                except Exception:
                    # Never return a pooled connection with a possibly held
                    # session-level advisory lock.
                    connection.invalidate()
                    raise
        return
    with _local_key_locks_guard:
        lock = _local_key_locks.setdefault(key, threading.Lock())
    with lock:
        yield
