"""RB-022: separate release authorities, versioned scope and bound admissions.

No authorities, releases or approvals are seeded. Existing invitations remain
unbound and therefore cannot admit anyone under the new gate.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_real_beta_release_governance"
down_revision = "0012_substantive_private_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Test/legacy SQLite databases may have been created from current metadata
    # before Alembic stamps its baseline. Production still runs each DDL once.
    inspector = sa.inspect(op.get_bind())
    if "release_authorities" not in inspector.get_table_names():
        op.create_table(
        "release_authorities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("authority_type", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("authority_type IN ('OWNER_APPROVER', 'PROFESSIONAL_APPROVER')", name="ck_release_authority_type"),
        )
    if "real_beta_releases" not in inspector.get_table_names():
        op.create_table(
        "real_beta_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("families_json", sa.JSON(), nullable=False),
        sa.Column("cohort_user_ids_json", sa.JSON(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_cases_total", sa.Integer(), nullable=False),
        sa.Column("max_active_cases_per_user", sa.Integer(), nullable=False),
        sa.Column("max_daily_admissions", sa.Integer(), nullable=False),
        sa.Column("max_duration_days", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'OPEN', 'CLOSED', 'REVOKED')", name="ck_real_beta_release_status"),
        sa.CheckConstraint("version >= 1", name="ck_real_beta_release_version"),
        )
    if "release_approvals" not in inspector.get_table_names():
        op.create_table(
        "release_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("real_beta_releases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("release_version", sa.Integer(), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("authority_id", sa.String(36), sa.ForeignKey("release_authorities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("authority_type", sa.String(30), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", "authority_id", "release_version", name="uq_release_approval_authority_version"),
        )
    inspector = sa.inspect(op.get_bind())
    if "ix_release_approvals_release_id" not in {item["name"] for item in inspector.get_indexes("release_approvals")}:
        op.create_index("ix_release_approvals_release_id", "release_approvals", ["release_id"])
    invitation_columns = {item["name"] for item in inspector.get_columns("real_beta_invitations")}
    if "release_id" not in invitation_columns:
        with op.batch_alter_table("real_beta_invitations") as batch:
            batch.add_column(sa.Column("release_id", sa.String(36), sa.ForeignKey(
                "real_beta_releases.id", ondelete="RESTRICT", name="fk_real_beta_invitation_release",
            )))
    if "intended_user_id" not in invitation_columns:
        with op.batch_alter_table("real_beta_invitations") as batch:
            batch.add_column(sa.Column("intended_user_id", sa.String(36), sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_real_beta_invitation_target",
            )))
    inspector = sa.inspect(op.get_bind())
    if "ix_real_beta_invitations_release_id" not in {item["name"] for item in inspector.get_indexes("real_beta_invitations")}:
        op.create_index("ix_real_beta_invitations_release_id", "real_beta_invitations", ["release_id"])
    if "real_beta_release_id" not in {item["name"] for item in inspector.get_columns("cases")}:
        with op.batch_alter_table("cases") as batch:
            batch.add_column(sa.Column("real_beta_release_id", sa.String(36), sa.ForeignKey(
                "real_beta_releases.id", ondelete="RESTRICT", name="fk_case_real_beta_release",
            )))
    inspector = sa.inspect(op.get_bind())
    if "ix_cases_real_beta_release_id" not in {item["name"] for item in inspector.get_indexes("cases")}:
        op.create_index("ix_cases_real_beta_release_id", "cases", ["real_beta_release_id"])


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_index("ix_cases_real_beta_release_id")
        batch.drop_column("real_beta_release_id")
    with op.batch_alter_table("real_beta_invitations") as batch:
        batch.drop_index("ix_real_beta_invitations_release_id")
        batch.drop_column("intended_user_id")
        batch.drop_column("release_id")
    op.drop_index("ix_release_approvals_release_id", table_name="release_approvals")
    op.drop_table("release_approvals")
    op.drop_table("real_beta_releases")
    op.drop_table("release_authorities")
