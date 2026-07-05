"""Revive plaid_accounts with owner + visibility

Revision ID: 011_revive_plaid_accounts
Revises: 010_add_households_and_users
Create Date: 2026-07-03

A bank account under a Plaid Item carries the ownership (``owner_user_id`` /
``household_id``) and ``visibility`` that per-account privacy is expressed
through. Financial rows denormalize these from here so RLS stays join-free.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_revive_plaid_accounts"
down_revision: str | Sequence[str] | None = "010_add_households_and_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plaid_accounts",
        sa.Column("account_id", sa.String(), primary_key=True),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "visibility",
            sa.String(),
            nullable=False,
            server_default=sa.text("'private'"),
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["plaid_items.item_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["household_id"], ["households.household_id"]),
    )


def downgrade() -> None:
    op.drop_table("plaid_accounts")
