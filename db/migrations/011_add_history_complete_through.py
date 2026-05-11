"""Add history_complete_through to amazon_login_profiles.

Revision ID: 011_add_history_complete_through
Revises: 010_add_profile_id_to_amazon_orders
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_add_history_complete_through"
down_revision: str | Sequence[str] | None = "010_add_profile_id_to_amazon_orders"


def upgrade() -> None:
    op.add_column(
        "amazon_login_profiles",
        sa.Column("history_complete_through", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("amazon_login_profiles", "history_complete_through")
