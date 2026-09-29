"""Add a closed, server-owned real-beta lane and private invitations."""

import sqlalchemy as sa
from alembic import op

revision = "0008_real_beta_admission"
down_revision = "0007_communication_occurred_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "mode" not in {column["name"] for column in inspector.get_columns("cases")}:
        op.add_column(
            "cases",
            sa.Column("mode", sa.String(20), nullable=False, server_default="SYNTHETIC"),
        )
    if "real_beta_invitations" in inspector.get_table_names():
        return
    op.create_table(
        "real_beta_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_real_beta_invitations_token_digest", "real_beta_invitations", ["token_digest"], unique=True)
    op.create_index("ix_real_beta_invitations_accepted_by_user_id", "real_beta_invitations", ["accepted_by_user_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "real_beta_invitations" in inspector.get_table_names():
        op.drop_index("ix_real_beta_invitations_accepted_by_user_id", table_name="real_beta_invitations")
        op.drop_index("ix_real_beta_invitations_token_digest", table_name="real_beta_invitations")
        op.drop_table("real_beta_invitations")
    if "mode" in {column["name"] for column in inspector.get_columns("cases")}:
        op.drop_column("cases", "mode")
