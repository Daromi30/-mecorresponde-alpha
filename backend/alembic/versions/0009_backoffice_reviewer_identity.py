"""Add individual, revocable backoffice identities and structured audit actors."""

import sqlalchemy as sa
from alembic import op

revision = "0009_backoffice_reviewer_identity"
down_revision = "0008_real_beta_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reviewers" not in tables:
        op.create_table(
            "reviewers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("login_id", sa.String(120), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("disabled_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("role IN ('reviewer', 'operator')", name="ck_reviewer_role"),
        )
        op.create_index("ix_reviewers_login_id", "reviewers", ["login_id"], unique=True)
    if "reviewer_sessions" not in tables:
        op.create_table(
            "reviewer_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("reviewers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_digest", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_reviewer_sessions_reviewer_id", "reviewer_sessions", ["reviewer_id"])
        op.create_index("ix_reviewer_sessions_token_digest", "reviewer_sessions", ["token_digest"], unique=True)
    if "actor_reviewer_id" not in {column["name"] for column in inspector.get_columns("audit_events")}:
        op.add_column("audit_events", sa.Column("actor_reviewer_id", sa.String(36), nullable=True))
        if bind.dialect.name == "postgresql":
            op.create_foreign_key(
                "fk_audit_events_actor_reviewer_id", "audit_events", "reviewers",
                ["actor_reviewer_id"], ["id"], ondelete="RESTRICT",
            )
        op.create_index("ix_audit_events_actor_reviewer_id", "audit_events", ["actor_reviewer_id"])
    if "assigned_reviewer_id" not in {column["name"] for column in inspector.get_columns("human_reviews")}:
        op.add_column("human_reviews", sa.Column("assigned_reviewer_id", sa.String(36), nullable=True))
        if bind.dialect.name == "postgresql":
            op.create_foreign_key(
                "fk_human_reviews_assigned_reviewer_id", "human_reviews", "reviewers",
                ["assigned_reviewer_id"], ["id"], ondelete="SET NULL",
            )
        op.create_index("ix_human_reviews_assigned_reviewer_id", "human_reviews", ["assigned_reviewer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "assigned_reviewer_id" in {column["name"] for column in inspector.get_columns("human_reviews")}:
        op.drop_index("ix_human_reviews_assigned_reviewer_id", table_name="human_reviews")
        if bind.dialect.name == "postgresql":
            op.drop_constraint("fk_human_reviews_assigned_reviewer_id", "human_reviews", type_="foreignkey")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("human_reviews", recreate="always") as batch:
                batch.drop_column("assigned_reviewer_id")
        else:
            op.drop_column("human_reviews", "assigned_reviewer_id")
    if "actor_reviewer_id" in {column["name"] for column in inspector.get_columns("audit_events")}:
        op.drop_index("ix_audit_events_actor_reviewer_id", table_name="audit_events")
        if bind.dialect.name == "postgresql":
            op.drop_constraint("fk_audit_events_actor_reviewer_id", "audit_events", type_="foreignkey")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("audit_events", recreate="always") as batch:
                batch.drop_column("actor_reviewer_id")
        else:
            op.drop_column("audit_events", "actor_reviewer_id")
    if "reviewer_sessions" in tables:
        op.drop_index("ix_reviewer_sessions_token_digest", table_name="reviewer_sessions")
        op.drop_index("ix_reviewer_sessions_reviewer_id", table_name="reviewer_sessions")
        op.drop_table("reviewer_sessions")
    if "reviewers" in tables:
        op.drop_index("ix_reviewers_login_id", table_name="reviewers")
        op.drop_table("reviewers")
