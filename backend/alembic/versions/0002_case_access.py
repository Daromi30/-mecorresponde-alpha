"""Protect anonymous cases with a hashed access token."""

import sqlalchemy as sa
from alembic import op

revision = "0002_case_access"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "case_access" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "case_access",
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("case_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "case_access" in sa.inspect(bind).get_table_names():
        op.drop_table("case_access")
