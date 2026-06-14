from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_m4_code_symbols"
down_revision = "0003_m3_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_code_symbols_workspace_project", "code_symbols", ["workspace_id", "project_id"])
    op.create_index("ix_code_symbols_resource", "code_symbols", ["resource_id"])
    op.create_index("ix_code_symbols_snapshot", "code_symbols", ["source_snapshot_id"])
    op.create_index("ix_code_symbols_name", "code_symbols", ["name"])
    op.execute("CREATE INDEX ix_code_symbols_search ON code_symbols USING gin (to_tsvector('simple', name || ' ' || path || ' ' || signature))")


def downgrade() -> None:
    op.drop_index("ix_code_symbols_search", table_name="code_symbols")
    op.drop_index("ix_code_symbols_name", table_name="code_symbols")
    op.drop_index("ix_code_symbols_snapshot", table_name="code_symbols")
    op.drop_index("ix_code_symbols_resource", table_name="code_symbols")
    op.drop_index("ix_code_symbols_workspace_project", table_name="code_symbols")
    op.drop_table("code_symbols")
