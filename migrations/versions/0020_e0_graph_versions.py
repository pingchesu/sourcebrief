"""Add graph version storage for E0.

Revision ID: 0020_e0_graph_versions
Revises: 0019_d_repo_agents
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_e0_graph_versions"
down_revision = "0019_d_repo_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graphs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("graph_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("graph_type", sa.Text(), nullable=False, server_default="resource"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_graphs_resource_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_graphs_id_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", "resource_id", name="uq_graphs_id_resource_scope"),
        sa.UniqueConstraint("workspace_id", "project_id", "graph_key", name="uq_graphs_key"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_graphs_status"),
        sa.CheckConstraint("graph_type = 'resource'", name="ck_graphs_type_e0"),
        sa.CheckConstraint("graph_key ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name="ck_graphs_key_format"),
    )
    op.create_index("uq_graphs_resource_active", "graphs", ["workspace_id", "project_id", "resource_id"], unique=True, postgresql_where=sa.text("resource_id IS NOT NULL"))
    op.create_index("ix_graphs_workspace_project", "graphs", ["workspace_id", "project_id"])

    op.create_table(
        "graph_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("membership_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["invalidated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["graph_id", "workspace_id", "project_id"], ["graphs.id", "graphs.workspace_id", "graphs.project_id"], name="fk_graph_versions_graph_scope"),
        sa.ForeignKeyConstraint(["graph_id", "workspace_id", "project_id", "resource_id"], ["graphs.id", "graphs.workspace_id", "graphs.project_id", "graphs.resource_id"], name="fk_graph_versions_graph_resource_scope"),
        sa.ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_graph_versions_resource_scope"),
        sa.ForeignKeyConstraint(["source_snapshot_id", "workspace_id", "project_id", "resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_graph_versions_snapshot_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_graph_versions_id_scope"),
        sa.UniqueConstraint("graph_id", "version", name="uq_graph_versions_graph_version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded', 'invalidated')", name="ck_graph_versions_status"),
        sa.CheckConstraint("version >= 1", name="ck_graph_versions_version_positive"),
        sa.CheckConstraint("version_hash LIKE 'sha256:%' AND length(version_hash) = 71", name="ck_graph_versions_hash_format"),
        sa.CheckConstraint("node_count >= 0", name="ck_graph_versions_node_count_nonnegative"),
        sa.CheckConstraint("edge_count >= 0", name="ck_graph_versions_edge_count_nonnegative"),
    )
    op.create_index("ix_graph_versions_graph_status", "graph_versions", ["graph_id", "status"])
    op.create_index("ix_graph_versions_resource_snapshot", "graph_versions", ["resource_id", "source_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_graph_versions_resource_snapshot", table_name="graph_versions")
    op.drop_index("ix_graph_versions_graph_status", table_name="graph_versions")
    op.drop_table("graph_versions")
    op.drop_index("ix_graphs_workspace_project", table_name="graphs")
    op.drop_index("uq_graphs_resource_active", table_name="graphs")
    op.drop_table("graphs")
