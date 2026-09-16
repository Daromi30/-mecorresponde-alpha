"""Store the real calendar date when a communication occurred."""

import sqlalchemy as sa
from alembic import op

revision = "0007_communication_occurred_on"
down_revision = "0006_outcome_resolved_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "communications" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("communications")}
    if "occurred_on" not in columns:
        op.add_column("communications", sa.Column("occurred_on", sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "communications" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("communications")}
    if "occurred_on" in columns:
        op.drop_column("communications", "occurred_on")
