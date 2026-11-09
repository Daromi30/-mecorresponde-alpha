"""Separate technical rule readiness from professional legal approval."""

import sqlalchemy as sa
from alembic import op


revision = "0015_legal_rule_governance"
down_revision = "0014_derived_invalidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    rules = sa.table(
        "legal_rule_versions",
        sa.column("review_status", sa.String()),
        sa.column("reviewed_by", sa.String()),
    )
    op.execute(
        rules.update()
        .where(rules.c.review_status == "approved")
        .where(sa.or_(rules.c.reviewed_by.is_(None), rules.c.reviewed_by == ""))
        .values(review_status="technical_draft")
    )


def downgrade() -> None:
    rules = sa.table("legal_rule_versions", sa.column("review_status", sa.String()))
    op.execute(
        rules.update()
        .where(rules.c.review_status == "technical_draft")
        .values(review_status="approved")
    )
