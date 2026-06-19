from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_product_auth_admin"
down_revision = "0012_m29_patch_pr_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("api_tokens", sa.Column("token_type", sa.Text(), nullable=False, server_default="api"))


def downgrade() -> None:
    op.drop_column("api_tokens", "token_type")
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")
