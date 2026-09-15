"""Adopt the current MECORRESPONDE schema as Alembic baseline.

This migration is intentionally idempotent for the existing alpha database:
SQLAlchemy creates any missing current tables without dropping or rewriting
existing data. Future schema changes must use explicit Alembic migrations.
"""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import Base
    import app.models  # noqa: F401
    import app.reviews  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Baseline adoption is deliberately non-destructive.
    pass
