from sqlalchemy import inspect, text

import app.models  # noqa: F401
import app.reviews  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.migrations import upgrade_database
from app.models import Case


def drop_version_table() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_alembic_adopts_existing_alpha_and_builds_empty_database():
    # 1) Simulate the already-deployed pre-Alembic alpha.
    Base.metadata.drop_all(bind=engine)
    drop_version_table()
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        case = Case(status="INTAKE", vertical="electricity", family="E04-B", raw_intake="migration sentinel")
        db.add(case)
        db.commit()
        sentinel_id = case.id

    upgrade_database()

    with SessionLocal() as db:
        assert db.get(Case, sentinel_id) is not None
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0002_case_access"

    tables = set(inspect(engine).get_table_names())
    assert "case_access" in tables

    # 2) The migration chain must also bootstrap a fresh database.
    Base.metadata.drop_all(bind=engine)
    drop_version_table()
    upgrade_database()

    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    assert "cases" in tables
    assert "case_access" in tables
    assert "documents" in tables
    assert "human_reviews" in tables
    assert "legal_rule_versions" in tables
