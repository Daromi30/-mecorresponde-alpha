"""Mark public closed-demo cases without altering historical synthetic cases."""

import sqlalchemy as sa
from alembic import op

revision = "0010_closed_demo_scenarios"
down_revision = "0009_backoffice_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "demo_scenario_id" not in {column["name"] for column in inspector.get_columns("cases")}:
        op.add_column("cases", sa.Column("demo_scenario_id", sa.String(80), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "demo_scenario_id" in {column["name"] for column in inspector.get_columns("cases")}:
        op.drop_column("cases", "demo_scenario_id")
