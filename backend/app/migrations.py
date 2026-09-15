from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import Base, engine


LEGACY_TABLES = {
    "cases",
    "facts",
    "documents",
    "evidence",
    "legal_sources",
    "legal_rule_versions",
}


def _config(connection) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.attributes["connection"] = connection
    return config


def upgrade_database() -> None:
    """Safely adopt legacy alpha databases or upgrade an already-managed database."""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        config = _config(connection)

        if "alembic_version" in tables:
            command.upgrade(config, "head")
            return

        if tables & LEGACY_TABLES:
            # The database predates Alembic. Preserve it, mark its known schema as
            # baseline, then apply only migrations introduced after that baseline.
            command.stamp(config, "0001_baseline")
            command.upgrade(config, "head")
            return

        # Brand-new database: create the current schema once, then mark it at head.
        # Existing databases never take this path, so historical migrations remain
        # the source of truth for upgrades without replaying obsolete bootstrap DDL.
        import app.models  # noqa: F401
        import app.reviews  # noqa: F401
        import app.security  # noqa: F401

        Base.metadata.create_all(bind=connection)
        command.stamp(config, "head")
