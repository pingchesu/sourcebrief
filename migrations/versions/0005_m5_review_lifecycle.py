from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_m5_review_lifecycle"
down_revision = "0004_m4_code_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("review_status", sa.Text(), nullable=False, server_default="unreviewed"))
    op.add_column("resources", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("resources", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("resources", sa.Column("last_reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("resources", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("resources", sa.Column("stale_after_days", sa.Integer(), nullable=False, server_default="30"))
    op.create_check_constraint(
        "ck_resources_review_status",
        "resources",
        "review_status IN ('approved', 'needs_update', 'stale', 'ignored', 'unreviewed')",
    )
    op.create_check_constraint("ck_resources_stale_after_days", "resources", "stale_after_days >= 1")
    op.create_index("ix_resources_review_status", "resources", ["workspace_id", "project_id", "review_status"])
    op.create_index("ix_resources_archived_at", "resources", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_resources_archived_at", table_name="resources")
    op.drop_index("ix_resources_review_status", table_name="resources")
    op.drop_constraint("ck_resources_stale_after_days", "resources", type_="check")
    op.drop_constraint("ck_resources_review_status", "resources", type_="check")
    op.drop_column("resources", "stale_after_days")
    op.drop_column("resources", "archived_at")
    op.drop_column("resources", "last_reviewed_by")
    op.drop_column("resources", "last_reviewed_at")
    op.drop_column("resources", "review_note")
    op.drop_column("resources", "review_status")
