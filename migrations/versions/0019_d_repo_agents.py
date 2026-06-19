"""Add repo agent v0 lifecycle tables for D.

Revision ID: 0019_d_repo_agents
Revises: 0018_c_skill_exports
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_d_repo_agents"
down_revision = "0018_c_skill_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repo_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_key", sa.Text(), nullable=False),
        sa.Column("pack_key", sa.Text(), nullable=False, server_default="default"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("update_policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{\"mode\":\"manual\"}'::jsonb")),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_repo_agents_id_scope"),
        sa.UniqueConstraint("workspace_id", "project_id", "agent_key", name="uq_repo_agents_key"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_repo_agents_status"),
        sa.CheckConstraint("agent_key ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name="ck_repo_agents_key_format"),
    )
    op.create_index("uq_repo_agents_resource_pack_active", "repo_agents", ["workspace_id", "project_id", "resource_id", "pack_key"], unique=True, postgresql_where=sa.text("resource_id IS NOT NULL"))

    op.create_table(
        "repo_agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repo_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_pack_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_export_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("diff_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("install_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rollback_from_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scrubbed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["repo_agent_id", "workspace_id", "project_id"], ["repo_agents.id", "repo_agents.workspace_id", "repo_agents.project_id"], name="fk_repo_agent_versions_agent_scope"),
        sa.ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_repo_agent_versions_resource_scope"),
        sa.ForeignKeyConstraint(["source_snapshot_id", "workspace_id", "project_id", "resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_repo_agent_versions_snapshot_scope"),
        sa.ForeignKeyConstraint(["resource_manifest_id", "workspace_id", "project_id", "resource_id"], ["resource_manifests.id", "resource_manifests.workspace_id", "resource_manifests.project_id", "resource_manifests.resource_id"], name="fk_repo_agent_versions_manifest_scope"),
        sa.ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_repo_agent_versions_pack_scope"),
        sa.ForeignKeyConstraint(["skill_export_id", "workspace_id", "project_id"], ["skill_exports.id", "skill_exports.workspace_id", "skill_exports.project_id"], name="fk_repo_agent_versions_skill_export_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_repo_agent_versions_id_scope"),
        sa.UniqueConstraint("repo_agent_id", "version", name="uq_repo_agent_versions_agent_version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded', 'invalidated', 'failed')", name="ck_repo_agent_versions_status"),
        sa.CheckConstraint("version >= 1", name="ck_repo_agent_versions_version_positive"),
        sa.CheckConstraint("version_hash LIKE 'sha256:%' AND length(version_hash) = 71", name="ck_repo_agent_versions_hash_format"),
    )
    op.create_index("ix_repo_agent_versions_agent_status", "repo_agent_versions", ["repo_agent_id", "status"])
    op.create_index("ix_repo_agent_versions_active_draft_hash", "repo_agent_versions", ["repo_agent_id", "version_hash"], unique=True, postgresql_where=sa.text("status = 'draft'"))


def downgrade() -> None:
    op.drop_index("ix_repo_agent_versions_active_draft_hash", table_name="repo_agent_versions")
    op.drop_index("ix_repo_agent_versions_agent_status", table_name="repo_agent_versions")
    op.drop_table("repo_agent_versions")
    op.drop_index("uq_repo_agents_resource_pack_active", table_name="repo_agents")
    op.drop_table("repo_agents")
