"""Add provider-neutral user accounts and external OIDC identities."""

import sqlalchemy as sa
from alembic import op

revision = "0003_accounts"
down_revision = "0002_case_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "user_accounts" not in tables:
        op.create_table(
            "user_accounts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_user_accounts_status", "user_accounts", ["status"], unique=False)
        op.create_index("ix_user_accounts_email", "user_accounts", ["email"], unique=False)

    tables = set(sa.inspect(bind).get_table_names())
    if "external_identities" not in tables:
        op.create_table(
            "external_identities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("provider", sa.String(length=80), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("email_snapshot", sa.String(length=320), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "subject", name="uq_external_identity_provider_subject"),
        )
        op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "external_identities" in tables:
        op.drop_index("ix_external_identities_user_id", table_name="external_identities")
        op.drop_table("external_identities")
    tables = set(sa.inspect(bind).get_table_names())
    if "user_accounts" in tables:
        op.drop_index("ix_user_accounts_email", table_name="user_accounts")
        op.drop_index("ix_user_accounts_status", table_name="user_accounts")
        op.drop_table("user_accounts")
