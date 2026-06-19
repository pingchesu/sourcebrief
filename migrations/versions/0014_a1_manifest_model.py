"""Add resource_manifests and resource_manifest_files for Milestone A1.

Revision ID: 0014_a1_manifest_model
Revises: 0013_product_auth_admin
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_a1_manifest_model"
down_revision = "0013_product_auth_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_source_snapshots_id_scope",
        "source_snapshots",
        ["id", "workspace_id", "project_id", "resource_id"],
    )

    op.create_table(
        "resource_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("parser_warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsupported_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_snapshot_id", name="uq_resource_manifests_snapshot"),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "project_id",
            "resource_id",
            name="uq_resource_manifests_id_scope",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "resource_id"],
            [
                "source_snapshots.id",
                "source_snapshots.workspace_id",
                "source_snapshots.project_id",
                "source_snapshots.resource_id",
            ],
            name="fk_resource_manifests_snapshot_scope",
        ),
        sa.CheckConstraint("file_count >= 0", name="ck_resource_manifests_file_count_nonnegative"),
        sa.CheckConstraint("total_bytes >= 0", name="ck_resource_manifests_total_bytes_nonnegative"),
        sa.CheckConstraint(
            "parser_warning_count >= 0 AND parser_warning_count <= file_count",
            name="ck_resource_manifests_warning_count_bounds",
        ),
        sa.CheckConstraint(
            "unsupported_file_count >= 0 AND unsupported_file_count <= file_count",
            name="ck_resource_manifests_unsupported_count_bounds",
        ),
        sa.CheckConstraint(
            "manifest_hash LIKE 'sha256:%' AND length(manifest_hash) = 71",
            name="ck_resource_manifests_manifest_hash_format",
        ),
    )
    op.create_index("ix_resource_manifests_workspace", "resource_manifests", ["workspace_id"])
    op.create_index("ix_resource_manifests_workspace_project", "resource_manifests", ["workspace_id", "project_id"])
    op.create_index("ix_resource_manifests_resource", "resource_manifests", ["resource_id"])

    op.create_table(
        "resource_manifest_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resource_manifests.id"), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("display_path", sa.Text(), nullable=True),
        sa.Column("path_hash", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column(
            "mtime_client",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="untrusted client-reported mtime; display only",
        ),
        sa.Column("parser", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("extraction_policy_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "resource_manifest_id",
            "normalized_path",
            name="uq_resource_manifest_files_manifest_path",
        ),
        sa.ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "resource_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
            ],
            name="fk_resource_manifest_files_manifest_scope",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_resource_manifest_files_size_nonnegative"),
        sa.CheckConstraint("section_count >= 0", name="ck_resource_manifest_files_section_count_nonnegative"),
        sa.CheckConstraint(
            "status IN ('pending', 'parsed', 'failed', 'unsupported', 'skipped')",
            name="ck_resource_manifest_files_status",
        ),
        sa.CheckConstraint(
            "path_hash LIKE 'sha256:%' AND length(path_hash) = 71",
            name="ck_resource_manifest_files_path_hash_format",
        ),
        sa.CheckConstraint(
            "content_hash LIKE 'sha256:%' AND length(content_hash) = 71",
            name="ck_resource_manifest_files_content_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(warnings_json) = 'array'",
            name="ck_resource_manifest_files_warnings_array",
        ),
    )
    op.create_index("ix_resource_manifest_files_manifest", "resource_manifest_files", ["resource_manifest_id"])
    op.create_index("ix_resource_manifest_files_workspace", "resource_manifest_files", ["workspace_id"])
    op.create_index("ix_resource_manifest_files_resource", "resource_manifest_files", ["resource_id"])
    op.create_index("ix_resource_manifest_files_content_hash", "resource_manifest_files", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_resource_manifest_files_content_hash", table_name="resource_manifest_files")
    op.drop_index("ix_resource_manifest_files_resource", table_name="resource_manifest_files")
    op.drop_index("ix_resource_manifest_files_workspace", table_name="resource_manifest_files")
    op.drop_index("ix_resource_manifest_files_manifest", table_name="resource_manifest_files")
    op.drop_table("resource_manifest_files")

    op.drop_index("ix_resource_manifests_resource", table_name="resource_manifests")
    op.drop_index("ix_resource_manifests_workspace_project", table_name="resource_manifests")
    op.drop_index("ix_resource_manifests_workspace", table_name="resource_manifests")
    op.drop_table("resource_manifests")
    op.execute("ALTER TABLE source_snapshots DROP CONSTRAINT IF EXISTS uq_source_snapshots_id_scope")
