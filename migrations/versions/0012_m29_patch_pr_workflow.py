"""Add opt-in patch and PR workflow records.

Revision ID: 0012_m29_patch_pr_workflow
Revises: 0011_m28_agent_card_summaries
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_m29_patch_pr_workflow"
down_revision = "0011_m28_agent_card_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patch_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_tokens.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("source_branch", sa.Text(), nullable=True),
        sa.Column("target_branch", sa.Text(), nullable=True),
        sa.Column("indexed_commit", sa.Text(), nullable=True),
        sa.Column("base_commit", sa.Text(), nullable=True),
        sa.Column("branch_moved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warnings", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("files", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("unified_diff", sa.Text(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_patch_proposals_status",
        "patch_proposals",
        "status IN ('draft', 'approved', 'rejected', 'pr_opened')",
    )
    op.create_index("ix_patch_proposals_project", "patch_proposals", ["workspace_id", "project_id", "created_at"])
    op.create_index("ix_patch_proposals_resource", "patch_proposals", ["resource_id", "created_at"])

    op.create_table(
        "pr_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("patch_proposal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patch_proposals.id"), nullable=False),
        sa.Column("approver_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approver_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_tokens.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="recorded"),
        sa.Column("source_branch", sa.Text(), nullable=False),
        sa.Column("target_branch", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=False),
        sa.Column("approval_note", sa.Text(), nullable=False),
        sa.Column("github_pr_url", sa.Text(), nullable=True),
        sa.Column("external_ref", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_pr_requests_status",
        "pr_requests",
        "status IN ('recorded', 'opened', 'failed', 'cancelled')",
    )
    op.create_index("ix_pr_requests_project", "pr_requests", ["workspace_id", "project_id", "created_at"])
    op.create_index("ix_pr_requests_patch", "pr_requests", ["patch_proposal_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pr_requests_patch", table_name="pr_requests")
    op.drop_index("ix_pr_requests_project", table_name="pr_requests")
    op.drop_constraint("ck_pr_requests_status", "pr_requests", type_="check")
    op.drop_table("pr_requests")
    op.drop_index("ix_patch_proposals_resource", table_name="patch_proposals")
    op.drop_index("ix_patch_proposals_project", table_name="patch_proposals")
    op.drop_constraint("ck_patch_proposals_status", "patch_proposals", type_="check")
    op.drop_table("patch_proposals")
