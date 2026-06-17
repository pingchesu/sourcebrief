"""Add retrieval profile tracking to eval history.

Revision ID: 0010_m27_retrieval_profiles
Revises: 0009_m26_remote_code_files
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_m27_retrieval_profiles"
down_revision = "0009_m26_remote_code_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "retrieval_eval_runs",
        sa.Column("profile", sa.Text(), nullable=False, server_default="hybrid"),
    )
    op.create_index(
        "ix_retrieval_eval_runs_project_profile_created",
        "retrieval_eval_runs",
        ["workspace_id", "project_id", "profile", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_eval_runs_project_profile_created", table_name="retrieval_eval_runs")
    op.drop_column("retrieval_eval_runs", "profile")
