from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .models import Case


def case_for_update_statement(case_id: str) -> Select:
    """Select one case while serializing concurrent workflow mutations on PostgreSQL."""
    return select(Case).where(Case.id == case_id).with_for_update()


def lock_case_for_update(db: Session, case_id: str) -> Case | None:
    """Lock the case row until the surrounding transaction commits or rolls back.

    PostgreSQL emits SELECT ... FOR UPDATE. SQLite deliberately ignores the locking
    clause, which keeps local/unit tests compatible while production serialization is
    enforced by the deployed PostgreSQL database.
    """
    return db.scalar(case_for_update_statement(case_id))
