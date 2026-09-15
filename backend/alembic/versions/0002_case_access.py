"""Add anonymous per-case access credentials.

Existing pre-security alpha cases intentionally receive no access row and therefore
become inaccessible through protected HTTP endpoints. No real client data should
have been stored before this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_case_access"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_access",
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("case_id"),
    )


def downgrade() -> None:
    op.drop_table("case_access")
