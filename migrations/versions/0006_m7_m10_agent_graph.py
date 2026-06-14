from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_m7_m10_agent_graph"
down_revision = "0005_m5_review_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("default_runtime", sa.Text(), nullable=False, server_default="api"),
        sa.Column("system_prompt", sa.Text()),
        sa.Column("tool_policy", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_profiles_workspace", "agent_profiles", ["workspace_id"])
    op.create_index("ix_agent_profiles_workspace_project", "agent_profiles", ["workspace_id", "project_id"])
    op.create_check_constraint(
        "ck_agent_profiles_default_runtime",
        "agent_profiles",
        "default_runtime IN ('api', 'hermes', 'claude', 'codex', 'cursor')",
    )

    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("node_key", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_graph_nodes_snapshot_key", "graph_nodes", ["source_snapshot_id", "node_key"])
    op.create_index("ix_graph_nodes_workspace_project", "graph_nodes", ["workspace_id", "project_id"])
    op.create_index("ix_graph_nodes_snapshot", "graph_nodes", ["source_snapshot_id"])
    op.create_index("ix_graph_nodes_resource", "graph_nodes", ["resource_id"])
    op.create_index("ix_graph_nodes_type", "graph_nodes", ["node_type"])
    op.execute("CREATE INDEX ix_graph_nodes_search ON graph_nodes USING gin (to_tsvector('simple', label || ' ' || coalesce(path, '')))")

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_graph_edges_workspace_project", "graph_edges", ["workspace_id", "project_id"])
    op.create_index("ix_graph_edges_snapshot", "graph_edges", ["source_snapshot_id"])
    op.create_index("ix_graph_edges_source", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["target_node_id"])
    op.create_index("ix_graph_edges_type", "graph_edges", ["edge_type"])
    op.create_unique_constraint(
        "uq_graph_edges_snapshot_source_target_type",
        "graph_edges",
        ["source_snapshot_id", "source_node_id", "target_node_id", "edge_type"],
    )

    op.add_column("retrieval_hits", sa.Column("graph_score", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("retrieval_hits", "graph_score")
    op.drop_constraint("uq_graph_edges_snapshot_source_target_type", "graph_edges", type_="unique")
    op.drop_index("ix_graph_edges_type", table_name="graph_edges")
    op.drop_index("ix_graph_edges_target", table_name="graph_edges")
    op.drop_index("ix_graph_edges_source", table_name="graph_edges")
    op.drop_index("ix_graph_edges_snapshot", table_name="graph_edges")
    op.drop_index("ix_graph_edges_workspace_project", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.execute("DROP INDEX IF EXISTS ix_graph_nodes_search")
    op.drop_index("ix_graph_nodes_type", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_resource", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_snapshot", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_workspace_project", table_name="graph_nodes")
    op.drop_constraint("uq_graph_nodes_snapshot_key", "graph_nodes", type_="unique")
    op.drop_table("graph_nodes")
    op.drop_constraint("ck_agent_profiles_default_runtime", "agent_profiles", type_="check")
    op.drop_index("ix_agent_profiles_workspace_project", table_name="agent_profiles")
    op.drop_index("ix_agent_profiles_workspace", table_name="agent_profiles")
    op.drop_table("agent_profiles")
