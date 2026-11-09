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
    )
    op.execute(
        rules.update()
        .where(rules.c.review_status == "approved")
        .values(review_status="technical_draft")
    )


def downgrade() -> None:
    # Deliberately data-preserving. The historical ``approved`` value did not
    # prove professional approval, so a downgrade cannot safely reconstruct it.
    # Keeping ``technical_draft`` is conservative and prevents rollback from
    # manufacturing legal authority.
    pass
