from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

import app.auth_models  # noqa: F401
import app.models  # noqa: F401
import app.reviews  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.migrations import upgrade_database
from app.models import AuditEvent, Case


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
        assert revision == "0010_closed_demo_scenarios"
        assert db.get(Case, sentinel_id).mode == "SYNTHETIC"
        assert db.get(Case, sentinel_id).demo_scenario_id is None

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "case_access" in tables
    assert "users" in tables
    assert "user_sessions" in tables
    assert "email_action_tokens" in tables
    assert "auth_throttle_state" in tables
    assert "real_beta_invitations" in tables
    assert "reviewers" in tables
    assert "reviewer_sessions" in tables
    assert "actor_reviewer_id" in {column["name"] for column in inspector.get_columns("audit_events")}
    assert "assigned_reviewer_id" in {column["name"] for column in inspector.get_columns("human_reviews")}
    assert "mode" in {column["name"] for column in inspector.get_columns("cases")}
    assert "demo_scenario_id" in {column["name"] for column in inspector.get_columns("cases")}
    assert "resolved_on" in {column["name"] for column in inspector.get_columns("outcomes")}
    assert "occurred_on" in {column["name"] for column in inspector.get_columns("communications")}

    # 2) The migration chain must also bootstrap a fresh database.
    Base.metadata.drop_all(bind=engine)
    drop_version_table()
    upgrade_database()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "alembic_version" in tables
    assert "cases" in tables
    assert "case_access" in tables
    assert "users" in tables
    assert "user_sessions" in tables
    assert "email_action_tokens" in tables
    assert "auth_throttle_state" in tables
    assert "real_beta_invitations" in tables
    assert "reviewers" in tables
    assert "reviewer_sessions" in tables
    assert "mode" in {column["name"] for column in inspector.get_columns("cases")}
    assert "demo_scenario_id" in {column["name"] for column in inspector.get_columns("cases")}
    assert "documents" in tables
    assert "human_reviews" in tables
    assert "legal_rule_versions" in tables
    assert "resolved_on" in {column["name"] for column in inspector.get_columns("outcomes")}
    assert "occurred_on" in {column["name"] for column in inspector.get_columns("communications")}


def test_real_beta_migration_upgrades_legacy_rows_and_is_reversible():
    Base.metadata.drop_all(bind=engine)
    drop_version_table()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        case = Case(status="INTAKE", vertical="electricity", family="E04-B", raw_intake="synthetic migration sentinel")
        db.add(case)
        db.commit()
        sentinel_id = case.id
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE real_beta_invitations"))
        conn.execute(text("ALTER TABLE cases DROP COLUMN mode"))

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.stamp(config, "0007_communication_occurred_on")
    upgrade_database()
    with SessionLocal() as db:
        assert db.get(Case, sentinel_id).mode == "SYNTHETIC"
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0010_closed_demo_scenarios"
    assert "real_beta_invitations" in inspect(engine).get_table_names()

    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0007_communication_occurred_on")
    inspector = inspect(engine)
    assert "mode" not in {column["name"] for column in inspector.get_columns("cases")}
    assert "real_beta_invitations" not in inspector.get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM cases WHERE id = :id"), {"id": sentinel_id}).scalar_one() == sentinel_id


def test_reviewer_migration_from_0008_preserves_historical_audit_and_reverses():
    Base.metadata.drop_all(bind=engine)
    drop_version_table()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        case = Case(status="INTAKE", vertical="electricity", family="E02-A", raw_intake="synthetic sentinel")
        db.add(case)
        db.flush()
        event = AuditEvent(case_id=case.id, event_type="SYNTHETIC_SENTINEL", payload_json={})
        db.add(event)
        db.commit()
        case_id, event_id = case.id, event.id
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.stamp(config, "0009_backoffice_identity")
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0008_real_beta_admission")
    assert "reviewers" not in inspect(engine).get_table_names()
    upgrade_database()
    with SessionLocal() as db:
        assert db.get(Case, case_id).mode == "SYNTHETIC"
        assert db.get(AuditEvent, event_id).actor_reviewer_id is None
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0010_closed_demo_scenarios"
    assert "reviewers" in inspect(engine).get_table_names()

    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0008_real_beta_admission")
    inspector = inspect(engine)
    assert "reviewers" not in inspector.get_table_names()
    assert "actor_reviewer_id" not in {column["name"] for column in inspector.get_columns("audit_events")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM audit_events WHERE id = :id"), {"id": event_id}).scalar_one() == event_id
