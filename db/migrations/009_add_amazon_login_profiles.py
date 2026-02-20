"""Add amazon_login_profiles table.

Revision ID: 009_add_amazon_login_profiles
Revises: 008_add_web_search_summary
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_add_amazon_login_profiles"
down_revision: str | Sequence[str] | None = "008_add_web_search_summary"


def upgrade() -> None:
    op.create_table(
        "amazon_login_profiles",
        sa.Column("profile_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("profile_key", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("browserbase_context_id", sa.String(128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_auth_at", sa.DateTime(), nullable=True),
        sa.Column("last_auth_status", sa.String(32), nullable=True),
        sa.Column("last_auth_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("amazon_login_profiles")
