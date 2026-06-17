"""Add snapshot full-file artifacts for remote code tools.

Revision ID: 0009_m26_remote_code_files
Revises: 0008_mature_alpha_eval_history
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_m26_remote_code_files"
down_revision = "0008_mature_alpha_eval_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("is_binary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_snapshot_files_snapshot_path", "snapshot_files", ["source_snapshot_id", "path"])
    op.create_index("ix_snapshot_files_current_lookup", "snapshot_files", ["workspace_id", "project_id", "resource_id", "source_snapshot_id", "path"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_files_current_lookup", table_name="snapshot_files")
    op.drop_constraint("uq_snapshot_files_snapshot_path", "snapshot_files", type_="unique")
    op.drop_table("snapshot_files")
