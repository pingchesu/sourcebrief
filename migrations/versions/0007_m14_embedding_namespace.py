"""M14 embedding namespace hardening.

Revision ID: 0007_m14_embedding_namespace
Revises: 0006_m7_m10_agent_graph
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_m14_embedding_namespace"
down_revision = "0006_m7_m10_agent_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunk_embeddings", sa.Column("namespace", sa.Text(), nullable=True))
    op.add_column("chunk_embeddings", sa.Column("normalized", sa.Boolean(), nullable=True))
    op.execute(
        """
        UPDATE chunk_embeddings
        SET normalized = true,
            namespace = provider || chr(58) || model || chr(58) || 'd' || dimensions::text || chr(58) || 'l2'
        WHERE namespace IS NULL
        """
    )
    op.alter_column("chunk_embeddings", "namespace", nullable=False)
    op.alter_column("chunk_embeddings", "normalized", nullable=False)
    op.create_index(
        "ix_chunk_embeddings_namespace",
        "chunk_embeddings",
        ["workspace_id", "project_id", "namespace"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_namespace", table_name="chunk_embeddings")
    op.drop_column("chunk_embeddings", "normalized")
    op.drop_column("chunk_embeddings", "namespace")
