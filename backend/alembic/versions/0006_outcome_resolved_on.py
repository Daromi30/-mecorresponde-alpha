"""Store the user-confirmed calendar date when an outcome was fulfilled."""

import sqlalchemy as sa
from alembic import op

revision = "0006_outcome_resolved_on"
down_revision = "0005_auth_throttle_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "outcomes" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("outcomes")}
    if "resolved_on" not in columns:
        op.add_column("outcomes", sa.Column("resolved_on", sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "outcomes" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("outcomes")}
    if "resolved_on" in columns:
        op.drop_column("outcomes", "resolved_on")
