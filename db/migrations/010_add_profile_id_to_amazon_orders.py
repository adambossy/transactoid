"""Add profile_id FK to amazon_orders.

Revision ID: 010_add_profile_id_to_amazon_orders
Revises: 009_add_amazon_login_profiles
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_add_profile_id_to_amazon_orders"
down_revision: str | Sequence[str] | None = "009_add_amazon_login_profiles"


def upgrade() -> None:
    op.add_column(
        "amazon_orders",
        sa.Column("profile_id", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "fk_amazon_orders_profile_id",
        "amazon_orders",
        "amazon_login_profiles",
        ["profile_id"],
        ["profile_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_amazon_orders_profile_id",
        "amazon_orders",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_amazon_orders_profile_id", table_name="amazon_orders")
    op.drop_constraint(
        "fk_amazon_orders_profile_id", "amazon_orders", type_="foreignkey"
    )
    op.drop_column("amazon_orders", "profile_id")
