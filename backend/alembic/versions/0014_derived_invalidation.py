"""RB-028: persist explicit invalidation of derived decisions."""

import sqlalchemy as sa
from alembic import op


revision = "0014_derived_invalidation"
down_revision = "0013_real_beta_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("decisions")}
    if "invalidated_at" not in columns:
        with op.batch_alter_table("decisions") as batch:
            batch.add_column(sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("decisions")}
    if "invalidated_at" in columns:
        with op.batch_alter_table("decisions") as batch:
            batch.drop_column("invalidated_at")
