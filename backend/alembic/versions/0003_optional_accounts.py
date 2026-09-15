"""Add optional user accounts and revocable sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_optional_accounts"
down_revision = "0002_case_access"
branch_labels = None
depends_on = None


def _index_names(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_indexes(table) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    tables = set(sa.inspect(bind).get_table_names())
    if "user_sessions" not in tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        )
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)
        op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)

    if "cases" in tables and "ix_cases_user_id" not in _index_names(bind, "cases"):
        op.create_index("ix_cases_user_id", "cases", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "cases" in tables and "ix_cases_user_id" in _index_names(bind, "cases"):
        op.drop_index("ix_cases_user_id", table_name="cases")
    if "user_sessions" in tables:
        op.drop_table("user_sessions")
    if "users" in tables:
        op.drop_table("users")
