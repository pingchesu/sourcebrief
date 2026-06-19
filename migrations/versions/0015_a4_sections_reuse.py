"""Add section extraction and snapshot section lineage for A4.

Revision ID: 0015_a4_sections_reuse
Revises: 0014_a1_manifest_model
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_a4_sections_reuse"
down_revision = "0014_a1_manifest_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_resources_id_scope", "resources", ["id", "workspace_id", "project_id"])
    op.create_unique_constraint(
        "uq_resource_manifests_id_snapshot_scope",
        "resource_manifests",
        ["id", "workspace_id", "project_id", "resource_id", "source_snapshot_id"],
    )
    op.create_unique_constraint(
        "uq_resource_manifest_files_id_scope",
        "resource_manifest_files",
        ["id", "workspace_id", "project_id", "resource_id", "resource_manifest_id"],
    )

    op.add_column("resource_manifests", sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("resource_manifests", sa.Column("sections_reused_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("resource_manifests", sa.Column("sections_extracted_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("resource_manifests", sa.Column("sections_from_deleted_files_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("resource_manifests", sa.Column("sections_absent_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_resource_manifests_section_count_nonnegative", "resource_manifests", "section_count >= 0")
    op.create_check_constraint("ck_resource_manifests_sections_reused_nonnegative", "resource_manifests", "sections_reused_count >= 0")
    op.create_check_constraint("ck_resource_manifests_sections_extracted_nonnegative", "resource_manifests", "sections_extracted_count >= 0")
    op.create_check_constraint("ck_resource_manifests_sections_from_deleted_files_nonnegative", "resource_manifests", "sections_from_deleted_files_count >= 0")
    op.create_check_constraint("ck_resource_manifests_sections_absent_nonnegative", "resource_manifests", "sections_absent_count >= 0")

    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("section_family_resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("extraction_policy_hash", sa.Text(), nullable=False),
        sa.Column("section_hash", sa.Text(), nullable=False),
        sa.Column("occurrence_key", sa.Text(), nullable=False),
        sa.Column("logical_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "logical_key", name="uq_sections_project_logical_key"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", "section_family_resource_id", name="uq_sections_id_scope"),
        sa.ForeignKeyConstraint(
            ["section_family_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_sections_family_resource_scope",
        ),
        sa.CheckConstraint("content_bytes >= 0", name="ck_sections_content_bytes_nonnegative"),
        sa.CheckConstraint("ordinal >= 0", name="ck_sections_ordinal_nonnegative"),
        sa.CheckConstraint("section_hash LIKE 'sha256:%' AND length(section_hash) = 71", name="ck_sections_section_hash_format"),
        sa.CheckConstraint("content_hash LIKE 'sha256:%' AND length(content_hash) = 71", name="ck_sections_content_hash_format"),
    )
    op.create_index("ix_sections_workspace_project", "sections", ["workspace_id", "project_id"])
    op.create_index("ix_sections_family_path", "sections", ["section_family_resource_id", "normalized_path"])

    op.create_table(
        "snapshot_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version_resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("section_family_resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("resource_manifest_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resource_manifests.id"), nullable=False),
        sa.Column("resource_manifest_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resource_manifest_files.id"), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_from_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=True),
        sa.Column("reuse_status", sa.Text(), nullable=False, server_default="extracted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_snapshot_id", "resource_manifest_file_id", "ordinal", name="uq_snapshot_sections_snapshot_file_ordinal"),
        sa.ForeignKeyConstraint(
            ["version_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_snapshot_sections_version_resource_scope",
        ),
        sa.ForeignKeyConstraint(
            ["section_family_resource_id", "workspace_id", "project_id"],
            ["resources.id", "resources.workspace_id", "resources.project_id"],
            name="fk_snapshot_sections_family_resource_scope",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id", "workspace_id", "project_id", "version_resource_id"],
            ["source_snapshots.id", "source_snapshots.workspace_id", "source_snapshots.project_id", "source_snapshots.resource_id"],
            name="fk_snapshot_sections_snapshot_scope",
        ),
        sa.ForeignKeyConstraint(
            ["resource_manifest_id", "workspace_id", "project_id", "version_resource_id", "source_snapshot_id"],
            [
                "resource_manifests.id",
                "resource_manifests.workspace_id",
                "resource_manifests.project_id",
                "resource_manifests.resource_id",
                "resource_manifests.source_snapshot_id",
            ],
            name="fk_snapshot_sections_manifest_scope",
        ),
        sa.ForeignKeyConstraint(
            ["resource_manifest_file_id", "workspace_id", "project_id", "version_resource_id", "resource_manifest_id"],
            [
                "resource_manifest_files.id",
                "resource_manifest_files.workspace_id",
                "resource_manifest_files.project_id",
                "resource_manifest_files.resource_id",
                "resource_manifest_files.resource_manifest_id",
            ],
            name="fk_snapshot_sections_manifest_file_scope",
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "workspace_id", "project_id", "section_family_resource_id"],
            ["sections.id", "sections.workspace_id", "sections.project_id", "sections.section_family_resource_id"],
            name="fk_snapshot_sections_section_scope",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_snapshot_sections_ordinal_nonnegative"),
        sa.CheckConstraint("reuse_status IN ('reused', 'extracted')", name="ck_snapshot_sections_reuse_status"),
    )
    op.create_index("ix_snapshot_sections_snapshot", "snapshot_sections", ["source_snapshot_id"])
    op.create_index("ix_snapshot_sections_section", "snapshot_sections", ["section_id"])
    op.create_index("ix_snapshot_sections_version_path", "snapshot_sections", ["version_resource_id", "normalized_path"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_sections_version_path", table_name="snapshot_sections")
    op.drop_index("ix_snapshot_sections_section", table_name="snapshot_sections")
    op.drop_index("ix_snapshot_sections_snapshot", table_name="snapshot_sections")
    op.drop_table("snapshot_sections")
    op.drop_index("ix_sections_family_path", table_name="sections")
    op.drop_index("ix_sections_workspace_project", table_name="sections")
    op.drop_table("sections")
    op.drop_constraint("ck_resource_manifests_sections_absent_nonnegative", "resource_manifests", type_="check")
    op.drop_constraint("ck_resource_manifests_sections_from_deleted_files_nonnegative", "resource_manifests", type_="check")
    op.drop_constraint("ck_resource_manifests_sections_extracted_nonnegative", "resource_manifests", type_="check")
    op.drop_constraint("ck_resource_manifests_sections_reused_nonnegative", "resource_manifests", type_="check")
    op.drop_constraint("ck_resource_manifests_section_count_nonnegative", "resource_manifests", type_="check")
    op.drop_column("resource_manifests", "sections_absent_count")
    op.drop_column("resource_manifests", "sections_from_deleted_files_count")
    op.drop_column("resource_manifests", "sections_extracted_count")
    op.drop_column("resource_manifests", "sections_reused_count")
    op.drop_column("resource_manifests", "section_count")
    op.execute("ALTER TABLE resource_manifests DROP CONSTRAINT IF EXISTS uq_resource_manifests_id_snapshot_scope")
    op.execute("ALTER TABLE resources DROP CONSTRAINT IF EXISTS uq_resources_id_scope")
    op.execute("ALTER TABLE resource_manifest_files DROP CONSTRAINT IF EXISTS uq_resource_manifest_files_id_scope")
