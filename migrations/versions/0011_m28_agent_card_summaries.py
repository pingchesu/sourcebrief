"""Add agent card drift summaries.

Revision ID: 0011_m28_agent_card_summaries
Revises: 0010_m27_retrieval_profiles
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_m28_agent_card_summaries"
down_revision = "0010_m27_retrieval_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_card_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source", sa.Text(), nullable=False, server_default="auditor"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("suppressed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_agent_card_summaries_status",
        "agent_card_summaries",
        "status IN ('healthy', 'stale', 'degraded', 'attention_needed', 'blocked')",
    )
    op.create_check_constraint(
        "ck_agent_card_summaries_severity",
        "agent_card_summaries",
        "severity IN ('info', 'warning', 'major', 'blocker')",
    )
    op.create_index(
        "ix_agent_card_summaries_latest",
        "agent_card_summaries",
        ["workspace_id", "project_id", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_agent_card_summaries_status",
        "agent_card_summaries",
        ["workspace_id", "project_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_card_summaries_status", table_name="agent_card_summaries")
    op.drop_index("ix_agent_card_summaries_latest", table_name="agent_card_summaries")
    op.drop_constraint("ck_agent_card_summaries_severity", "agent_card_summaries", type_="check")
    op.drop_constraint("ck_agent_card_summaries_status", "agent_card_summaries", type_="check")
    op.drop_table("agent_card_summaries")
