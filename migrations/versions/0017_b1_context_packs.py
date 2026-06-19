"""Add context pack versions for B1.

Revision ID: 0017_b1_context_packs
Revises: 0016_b0_context_artifacts
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_b1_context_packs"
down_revision = "0016_b0_context_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_context_packs_workspace"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_context_packs_project"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_context_packs_created_by"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_context_packs_id_scope"),
        sa.UniqueConstraint("workspace_id", "project_id", "pack_key", name="uq_context_packs_project_key"),
        sa.CheckConstraint("pack_key ~ '^[a-z0-9][a-z0-9._-]{0,62}$'", name="ck_context_packs_key_format"),
    )

    op.create_table(
        "context_pack_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_pack_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pack_hash", sa.Text(), nullable=False),
        sa.Column("coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rolled_back_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["invalidated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["context_pack_id", "workspace_id", "project_id"], ["context_packs.id", "context_packs.workspace_id", "context_packs.project_id"], name="fk_context_pack_versions_pack_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_context_pack_versions_id_scope"),
        sa.UniqueConstraint("workspace_id", "project_id", "pack_key", "version", name="uq_context_pack_versions_project_key_version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded', 'rolled_back', 'invalidated', 'failed')", name="ck_context_pack_versions_status"),
        sa.CheckConstraint("version >= 1", name="ck_context_pack_versions_version_positive"),
        sa.CheckConstraint("pack_hash LIKE 'sha256:%' AND length(pack_hash) = 71", name="ck_context_pack_versions_hash_format"),
    )
    op.create_index("uq_context_pack_versions_one_published", "context_pack_versions", ["workspace_id", "project_id", "pack_key"], unique=True, postgresql_where=sa.text("status = 'published'"))
    op.create_index("ix_context_pack_versions_project_key_status", "context_pack_versions", ["workspace_id", "project_id", "pack_key", "status"])
    op.create_index("ix_context_pack_versions_project_status_created", "context_pack_versions", ["workspace_id", "project_id", "status", "created_at"])

    op.create_table(
        "context_pack_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_pack_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_context_pack_artifacts_version_scope"),
        sa.ForeignKeyConstraint(["context_artifact_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id", "resource_manifest_id"], ["context_artifacts.id", "context_artifacts.workspace_id", "context_artifacts.project_id", "context_artifacts.resource_id", "context_artifacts.source_snapshot_id", "context_artifacts.resource_manifest_id"], name="fk_context_pack_artifacts_artifact_scope"),
        sa.UniqueConstraint("context_pack_version_id", "context_artifact_id", name="uq_context_pack_artifacts_version_artifact"),
        sa.UniqueConstraint("context_pack_version_id", "ordinal", name="uq_context_pack_artifacts_version_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_context_pack_artifacts_ordinal_nonnegative"),
        sa.CheckConstraint("artifact_hash LIKE 'sha256:%' AND length(artifact_hash) = 71", name="ck_context_pack_artifacts_hash_format"),
    )

    op.create_table(
        "context_pack_resource_coverage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_pack_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_context_pack_coverage_version_scope"),
        sa.ForeignKeyConstraint(["resource_id", "workspace_id", "project_id"], ["resources.id", "resources.workspace_id", "resources.project_id"], name="fk_context_pack_coverage_resource_scope"),
        sa.ForeignKeyConstraint(["source_snapshot_id", "workspace_id", "project_id", "resource_id"], ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"], name="fk_context_pack_coverage_snapshot_scope"),
        sa.UniqueConstraint("context_pack_version_id", "resource_id", "source_snapshot_id", "resource_manifest_id", name="uq_context_pack_coverage_version_resource_snapshot_manifest"),
        sa.CheckConstraint("artifact_count >= 0", name="ck_context_pack_coverage_artifact_count_nonnegative"),
        sa.CheckConstraint("citation_count >= 0", name="ck_context_pack_coverage_citation_count_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("context_pack_resource_coverage")
    op.drop_table("context_pack_artifacts")
    op.drop_index("ix_context_pack_versions_project_status_created", table_name="context_pack_versions")
    op.drop_index("ix_context_pack_versions_project_key_status", table_name="context_pack_versions")
    op.drop_index("uq_context_pack_versions_one_published", table_name="context_pack_versions")
    op.drop_table("context_pack_versions")
    op.drop_table("context_packs")
