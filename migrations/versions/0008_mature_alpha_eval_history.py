"""Persist mature-alpha retrieval eval history.

Revision ID: 0008_mature_alpha_eval_history
Revises: 0007_m14_embedding_namespace
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_mature_alpha_eval_history"
down_revision = "0007_m14_embedding_namespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_tokens.id"), nullable=True),
        sa.Column("runtime", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("project_wide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resource_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_retrieval_eval_runs_project_created",
        "retrieval_eval_runs",
        ["workspace_id", "project_id", "created_at"],
    )
    op.create_table(
        "retrieval_eval_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("retrieval_eval_runs.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_resource_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("cited_resource_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("forbidden_resource_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("failure_reasons", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("hit_quality", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_retrieval_eval_items_run_ordinal", "retrieval_eval_items", ["eval_run_id", "ordinal"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_eval_items_run_ordinal", table_name="retrieval_eval_items")
    op.drop_table("retrieval_eval_items")
    op.drop_index("ix_retrieval_eval_runs_project_created", table_name="retrieval_eval_runs")
    op.drop_table("retrieval_eval_runs")
