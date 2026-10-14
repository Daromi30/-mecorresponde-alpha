"""Explicit fail-closed technical family authorization for private reviewers."""

import sqlalchemy as sa
from alembic import op

revision = "0012_substantive_private_review"
down_revision = "0011_document_storage_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "reviewer_family_authorizations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "reviewer_family_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("reviewers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family", sa.String(20), nullable=False),
        sa.Column("granted_by_reviewer_id", sa.String(36), sa.ForeignKey("reviewers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reviewer_id", "family", name="uq_reviewer_family_authorization"),
    )
    op.create_index("ix_reviewer_family_authorizations_reviewer_id", "reviewer_family_authorizations", ["reviewer_id"])


def downgrade() -> None:
    if "reviewer_family_authorizations" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_reviewer_family_authorizations_reviewer_id", table_name="reviewer_family_authorizations")
    op.drop_table("reviewer_family_authorizations")
