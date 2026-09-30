"""Durable, provider-neutral document storage intents and tombstones."""

import sqlalchemy as sa
from alembic import op

revision = "0011_document_storage_reconciliation"
down_revision = "0010_closed_demo_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Test/startup environments can create ORM metadata before Alembic adopts it.
    if "document_storage_operations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "document_storage_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_type", sa.String(8), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("backend", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("cleanup_allowed", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=True),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_type", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("operation_type IN ('PUT', 'DELETE')", name="ck_document_storage_operation_type"),
        sa.CheckConstraint("state IN ('PENDING', 'CLEANUP', 'RETRY', 'BLOCKED', 'COMPLETE')", name="ck_document_storage_operation_state"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_document_storage_operation_attempts"),
    )
    op.create_index("ix_document_storage_operations_operation_type", "document_storage_operations", ["operation_type"])
    op.create_index("ix_document_storage_operations_storage_key", "document_storage_operations", ["storage_key"])
    op.create_index("ix_document_storage_operations_state", "document_storage_operations", ["state"])


def downgrade() -> None:
    if "document_storage_operations" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_document_storage_operations_state", table_name="document_storage_operations")
    op.drop_index("ix_document_storage_operations_storage_key", table_name="document_storage_operations")
    op.drop_index("ix_document_storage_operations_operation_type", table_name="document_storage_operations")
    op.drop_table("document_storage_operations")
