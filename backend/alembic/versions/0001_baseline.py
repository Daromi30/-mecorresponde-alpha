"""Mark the pre-Alembic MECORRESPONDE alpha schema as the baseline.

The deployed alpha already had its tables before Alembic was introduced, so this
revision intentionally performs no DDL. The application migration runner stamps
legacy databases at this revision and then applies later explicit migrations.
Fresh databases are bootstrapped from the current SQLAlchemy metadata and stamped
at the current head.
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
