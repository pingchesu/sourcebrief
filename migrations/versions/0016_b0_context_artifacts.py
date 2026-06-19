"""Add deterministic context artifacts for B0.

Revision ID: 0016_b0_context_artifacts
Revises: 0015_a4_sections_reuse
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_b0_context_artifacts"
down_revision = "0015_a4_sections_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_snapshot_sections_id_b0_scope",
        "snapshot_sections",
        [
            "id",
            "workspace_id",
            "project_id",
            "version_resource_id",
            "section_family_resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            "resource_manifest_file_id",
            "normalized_path",
        ],
    )

    op.create_table(
        "context_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("artifact_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("artifact_hash", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_context_artifacts_resource_scope",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "resource_id"],
            ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"],
            name="fk_context_artifacts_snapshot_scope",
        ),
        sa.ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
                "resource_manifests.source_snapshot_id",
            ],
            name="fk_context_artifacts_manifest_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            name="uq_context_artifacts_id_scope",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "resource_id",
            "source_snapshot_id",
            "artifact_type",
            "artifact_hash",
            "artifact_revision",
            name="uq_context_artifacts_hash_revision",
        ),
        sa.CheckConstraint("status IN ('draft', 'approved', 'rejected', 'failed')", name="ck_context_artifacts_status"),
        sa.CheckConstraint("artifact_revision >= 1", name="ck_context_artifacts_revision_positive"),
        sa.CheckConstraint("artifact_hash LIKE 'sha256:%' AND length(artifact_hash) = 71", name="ck_context_artifacts_hash_format"),
    )

    op.create_table(
        "context_artifact_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_status", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["context_artifact_id", "workspace_id", "project_id", "resource_id", "source_snapshot_id", "resource_manifest_id"],
            [
                "context_artifacts.id",
                "context_artifacts.workspace_id",
                "context_artifacts.project_id",
                "context_artifacts.resource_id",
                "context_artifacts.source_snapshot_id",
                "context_artifacts.resource_manifest_id",
            ],
            name="fk_context_artifact_sources_artifact_scope",
        ),
        sa.ForeignKeyConstraint(
            ["resource_manifest_file_id", "workspace_id", "project_id", "resource_id", "resource_manifest_id"],
            [
                "resource_manifest_files.id",
                "resource_manifest_files.workspace_id",
                "resource_manifest_files.project_id",
                "resource_manifest_files.resource_id",
                "resource_manifest_files.resource_manifest_id",
            ],
            name="fk_context_artifact_sources_manifest_file_scope",
        ),
        sa.UniqueConstraint("context_artifact_id", "normalized_path", name="uq_context_artifact_sources_artifact_path"),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "context_artifact_id",
            "resource_manifest_file_id",
            "resource_id",
            "source_snapshot_id",
            "resource_manifest_id",
            "normalized_path",
            name="uq_context_artifact_sources_id_scope",
        ),
        sa.CheckConstraint("section_count >= 0", name="ck_context_artifact_sources_section_count_nonnegative"),
        sa.CheckConstraint(
            "coverage_status IN ('covered', 'warning', 'empty', 'unsupported', 'failed', 'skipped')",
            name="ck_context_artifact_sources_coverage_status",
        ),
    )

    op.create_table(
        "context_artifact_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_artifact_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_family_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_manifest_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            [
                "snapshot_section_id",
                "workspace_id",
                "project_id",
                "resource_id",
                "section_family_resource_id",
                "source_snapshot_id",
                "resource_manifest_id",
                "resource_manifest_file_id",
                "normalized_path",
            ],
            [
                "snapshot_sections.id",
                "snapshot_sections.workspace_id",
                "snapshot_sections.project_id",
                "snapshot_sections.version_resource_id",
                "snapshot_sections.section_family_resource_id",
                "snapshot_sections.source_snapshot_id",
                "snapshot_sections.resource_manifest_id",
                "snapshot_sections.resource_manifest_file_id",
                "snapshot_sections.normalized_path",
            ],
            name="fk_context_artifact_citations_snapshot_section_scope",
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "workspace_id", "project_id", "section_family_resource_id"],
            ["sections.id", "sections.workspace_id", "sections.project_id", "sections.section_family_resource_id"],
            name="fk_context_artifact_citations_section_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "context_artifact_source_id",
                "workspace_id",
                "project_id",
                "context_artifact_id",
                "resource_manifest_file_id",
                "resource_id",
                "source_snapshot_id",
                "resource_manifest_id",
                "normalized_path",
            ],
            [
                "context_artifact_sources.id",
                "context_artifact_sources.workspace_id",
                "context_artifact_sources.project_id",
                "context_artifact_sources.context_artifact_id",
                "context_artifact_sources.resource_manifest_file_id",
                "context_artifact_sources.resource_id",
                "context_artifact_sources.source_snapshot_id",
                "context_artifact_sources.resource_manifest_id",
                "context_artifact_sources.normalized_path",
            ],
            name="fk_context_artifact_citations_source_scope",
        ),
        sa.UniqueConstraint("context_artifact_id", "snapshot_section_id", name="uq_context_artifact_citations_artifact_snapshot_section"),
        sa.CheckConstraint("ordinal >= 0", name="ck_context_artifact_citations_ordinal_nonnegative"),
        sa.CheckConstraint("content_hash LIKE 'sha256:%' AND length(content_hash) = 71", name="ck_context_artifact_citations_content_hash_format"),
    )


def downgrade() -> None:
    op.drop_table("context_artifact_citations")
    op.drop_table("context_artifact_sources")
    op.drop_table("context_artifacts")
    op.drop_constraint("uq_snapshot_sections_id_b0_scope", "snapshot_sections", type_="unique")
