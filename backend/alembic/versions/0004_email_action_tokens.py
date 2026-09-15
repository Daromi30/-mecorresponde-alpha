"""Add hashed one-time tokens for email verification and password reset."""

import sqlalchemy as sa
from alembic import op

revision = "0004_email_action_tokens"
down_revision = "0003_optional_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "email_action_tokens" in tables:
        return

    op.create_table(
        "email_action_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_action_tokens_token_hash"),
    )
    op.create_index("ix_email_action_tokens_user_id", "email_action_tokens", ["user_id"], unique=False)
    op.create_index("ix_email_action_tokens_purpose", "email_action_tokens", ["purpose"], unique=False)
    op.create_index("ix_email_action_tokens_token_hash", "email_action_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "email_action_tokens" in tables:
        op.drop_table("email_action_tokens")
