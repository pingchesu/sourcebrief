"""Add graph merge V0 tables.

Revision ID: 0021_e1_graph_merges
Revises: 0020_e0_graph_versions
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_e1_graph_merges"
down_revision = "0020_e0_graph_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_graph_versions_input_identity",
        "graph_versions",
        ["id", "workspace_id", "project_id", "graph_id", "resource_id", "source_snapshot_id"],
    )
    op.create_table(
        "graph_merges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merge_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_graph_merges_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("workspace_id", "project_id", "merge_key", name="uq_graph_merges_project_key"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_graph_merges_id_scope"),
    )
    op.create_table(
        "graph_merge_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_merge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("merge_strategy", sa.Text(), nullable=False),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("published_by", postgresql.UUID(as_uuid=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("status_reason", sa.Text()),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded', 'invalidated')", name="ck_graph_merge_versions_status"),
        sa.CheckConstraint("merge_strategy IN ('union', 'overlay')", name="ck_graph_merge_versions_strategy"),
        sa.CheckConstraint("version >= 1", name="ck_graph_merge_versions_version_positive"),
        sa.CheckConstraint("version_hash LIKE 'sha256:%' AND length(version_hash) = 71", name="ck_graph_merge_versions_hash_format"),
        sa.CheckConstraint("input_hash LIKE 'sha256:%' AND length(input_hash) = 71", name="ck_graph_merge_versions_input_hash_format"),
        sa.CheckConstraint("node_count >= 0", name="ck_graph_merge_versions_node_count_nonnegative"),
        sa.CheckConstraint("edge_count >= 0", name="ck_graph_merge_versions_edge_count_nonnegative"),
        sa.CheckConstraint("candidate_count >= 0", name="ck_graph_merge_versions_candidate_count_nonnegative"),
        sa.CheckConstraint("unresolved_candidate_count >= 0", name="ck_graph_merge_versions_unresolved_candidate_count_nonnegative"),
        sa.ForeignKeyConstraint(["graph_merge_id", "workspace_id", "project_id"], ["graph_merges.id", "graph_merges.workspace_id", "graph_merges.project_id"], name="fk_graph_merge_versions_merge_scope"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["invalidated_by"], ["users.id"]),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_graph_merge_versions_id_scope"),
        sa.UniqueConstraint("id", "graph_merge_id", "workspace_id", "project_id", name="uq_graph_merge_versions_current_scope"),
        sa.UniqueConstraint("graph_merge_id", "version", name="uq_graph_merge_versions_merge_version"),
    )
    op.create_foreign_key(
        "fk_graph_merges_current_version",
        "graph_merges",
        "graph_merge_versions",
        ["current_version_id", "id", "workspace_id", "project_id"],
        ["id", "graph_merge_id", "workspace_id", "project_id"],
    )
    op.create_index("ix_graph_merge_versions_merge_status", "graph_merge_versions", ["graph_merge_id", "status"])
    op.create_table(
        "graph_merge_inputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_merge_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_graph_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("input_version_hash", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "workspace_id", "project_id"], ["graph_merge_versions.id", "graph_merge_versions.workspace_id", "graph_merge_versions.project_id"], name="fk_graph_merge_inputs_version_scope"),
        sa.ForeignKeyConstraint(["input_graph_version_id", "workspace_id", "project_id", "input_graph_id", "input_resource_id", "input_source_snapshot_id"], ["graph_versions.id", "graph_versions.workspace_id", "graph_versions.project_id", "graph_versions.graph_id", "graph_versions.resource_id", "graph_versions.source_snapshot_id"], name="fk_graph_merge_inputs_graph_version_identity"),
        sa.ForeignKeyConstraint(["input_resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_graph_merge_inputs_resource_scope"),
        sa.ForeignKeyConstraint(["input_source_snapshot_id", "workspace_id", "project_id", "input_resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_graph_merge_inputs_snapshot_scope"),
        sa.UniqueConstraint("graph_merge_version_id", "input_graph_version_id", name="uq_graph_merge_inputs_version_input"),
        sa.UniqueConstraint("graph_merge_version_id", "input_resource_id", name="uq_graph_merge_inputs_version_resource"),
        sa.UniqueConstraint("graph_merge_version_id", "input_graph_id", name="uq_graph_merge_inputs_version_graph"),
        sa.UniqueConstraint("graph_merge_version_id", "ordinal", name="uq_graph_merge_inputs_version_ordinal"),
    )
    op.create_table(
        "graph_merge_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_merge_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merged_node_key", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("display_label", sa.Text(), nullable=False),
        sa.Column("origin_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "workspace_id", "project_id"], ["graph_merge_versions.id", "graph_merge_versions.workspace_id", "graph_merge_versions.project_id"], name="fk_graph_merge_nodes_version_scope"),
        sa.UniqueConstraint("graph_merge_version_id", "merged_node_key", name="uq_graph_merge_nodes_version_key"),
    )
    op.create_table(
        "graph_merge_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_merge_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_merged_node_key", sa.Text(), nullable=False),
        sa.Column("target_merged_node_key", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("origin_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "workspace_id", "project_id"], ["graph_merge_versions.id", "graph_merge_versions.workspace_id", "graph_merge_versions.project_id"], name="fk_graph_merge_edges_version_scope"),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "source_merged_node_key"], ["graph_merge_nodes.graph_merge_version_id", "graph_merge_nodes.merged_node_key"], name="fk_graph_merge_edges_source_node"),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "target_merged_node_key"], ["graph_merge_nodes.graph_merge_version_id", "graph_merge_nodes.merged_node_key"], name="fk_graph_merge_edges_target_node"),
        sa.UniqueConstraint("graph_merge_version_id", "source_merged_node_key", "target_merged_node_key", "edge_type", name="uq_graph_merge_edges_version_edge"),
    )
    op.create_table(
        "graph_merge_reconcile_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_merge_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_key", sa.Text(), nullable=False),
        sa.Column("candidate_type", sa.Text(), nullable=False),
        sa.Column("left_origin_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("right_origin_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("review_reason", sa.Text()),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("candidate_type IN ('same_path', 'same_label', 'same_symbol')", name="ck_graph_merge_candidates_type"),
        sa.CheckConstraint("status IN ('open', 'accepted', 'rejected')", name="ck_graph_merge_candidates_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_graph_merge_candidates_confidence"),
        sa.ForeignKeyConstraint(["graph_merge_version_id", "workspace_id", "project_id"], ["graph_merge_versions.id", "graph_merge_versions.workspace_id", "graph_merge_versions.project_id"], name="fk_graph_merge_candidates_version_scope"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.UniqueConstraint("graph_merge_version_id", "candidate_key", name="uq_graph_merge_candidates_version_key"),
    )


def downgrade() -> None:
    op.drop_table("graph_merge_reconcile_candidates")
    op.drop_table("graph_merge_edges")
    op.drop_table("graph_merge_nodes")
    op.drop_table("graph_merge_inputs")
    op.drop_constraint("fk_graph_merges_current_version", "graph_merges", type_="foreignkey")
    op.drop_index("ix_graph_merge_versions_merge_status", table_name="graph_merge_versions")
    op.drop_table("graph_merge_versions")
    op.drop_table("graph_merges")
    op.drop_constraint("uq_graph_versions_input_identity", "graph_versions", type_="unique")
