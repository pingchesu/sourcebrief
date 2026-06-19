"""Add generated skill exports for C.

Revision ID: 0018_c_skill_exports
Revises: 0017_b1_context_packs
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_c_skill_exports"
down_revision = "0017_b1_context_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_pack_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_key", sa.Text(), nullable=False),
        sa.Column("pack_version", sa.Integer(), nullable=False),
        sa.Column("export_type", sa.Text(), nullable=False, server_default="hermes_skill"),
        sa.Column("export_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("package_hash", sa.Text(), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("files_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("leak_scan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["invalidated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["context_pack_version_id", "workspace_id", "project_id"], ["context_pack_versions.id", "context_pack_versions.workspace_id", "context_pack_versions.project_id"], name="fk_skill_exports_pack_version_scope"),
        sa.UniqueConstraint("id", "workspace_id", "project_id", name="uq_skill_exports_id_scope"),
        sa.UniqueConstraint("workspace_id", "project_id", "context_pack_version_id", "export_type", "package_hash", name="uq_skill_exports_pack_type_hash"),
        sa.UniqueConstraint("workspace_id", "project_id", "context_pack_version_id", "export_type", "export_version", name="uq_skill_exports_pack_type_version"),
        sa.CheckConstraint("status IN ('draft', 'approved', 'rejected', 'invalidated', 'failed')", name="ck_skill_exports_status"),
        sa.CheckConstraint("export_type IN ('hermes_skill')", name="ck_skill_exports_type"),
        sa.CheckConstraint("export_version >= 1", name="ck_skill_exports_version_positive"),
        sa.CheckConstraint("package_hash LIKE 'sha256:%' AND length(package_hash) = 71", name="ck_skill_exports_hash_format"),
    )
    op.create_index("ix_skill_exports_pack_status", "skill_exports", ["workspace_id", "project_id", "context_pack_version_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_skill_exports_pack_status", table_name="skill_exports")
    op.drop_table("skill_exports")
