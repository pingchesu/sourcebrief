from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_m2_ingestion"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_snapshots",
        sa.Column(
            "version_kind",
            sa.Text(),
            nullable=False,
            server_default="content_hash",
        ),
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_chunks_workspace", "chunks", ["workspace_id"])
    op.create_index("ix_chunks_workspace_project", "chunks", ["workspace_id", "project_id"])
    op.create_index("ix_chunks_snapshot", "chunks", ["source_snapshot_id"])
    op.create_index("ix_chunks_resource", "chunks", ["resource_id"])
    # GIN full-text index backing basic lexical search. The explicit 'english'
    # regconfig keeps to_tsvector IMMUTABLE so it is valid in a functional index.
    op.execute(
        "CREATE INDEX ix_chunks_content_fts ON chunks "
        "USING gin (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_content_fts", table_name="chunks")
    op.drop_index("ix_chunks_resource", table_name="chunks")
    op.drop_index("ix_chunks_snapshot", table_name="chunks")
    op.drop_index("ix_chunks_workspace_project", table_name="chunks")
    op.drop_index("ix_chunks_workspace", table_name="chunks")
    op.drop_table("chunks")
    op.drop_column("source_snapshots", "version_kind")
