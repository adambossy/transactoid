"""Add nullable tenant columns to financial tables (expand phase)

Revision ID: 012_add_tenant_columns_nullable
Revises: 011_revive_plaid_accounts
Create Date: 2026-07-03

Expand half of the expand->backfill->contract sequence: every financial table
gains nullable ``household_id`` / ``owner_user_id`` / ``visibility`` columns,
denormalized so RLS policies stay join-free. ``plaid_items`` gets no
``visibility`` (an item's visibility is per-account, on ``plaid_accounts``);
household-term tables get only ``household_id``. Migration 013 backfills,
migration 014 tightens to NOT NULL + FKs.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_add_tenant_columns_nullable"
down_revision: str | Sequence[str] | None = "011_revive_plaid_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_VIS = [
    "plaid_transactions",
    "derived_transactions",
    "transaction_items",
    "transaction_tags",
    "email_receipts",
    "pending_receipt_matches",
    "account_sign_conventions",
    "amazon_login_profiles",
    "amazon_orders",
    "amazon_items",
]
HOUSEHOLD_ONLY = ["tags", "transaction_category_events"]


def upgrade() -> None:
    for t in OWNER_VIS:
        op.add_column(t, sa.Column("household_id", sa.Uuid(), nullable=True))
        op.add_column(t, sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        op.add_column(t, sa.Column("visibility", sa.String(), nullable=True))
    op.add_column("plaid_items", sa.Column("household_id", sa.Uuid(), nullable=True))
    op.add_column("plaid_items", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    for t in HOUSEHOLD_ONLY:
        op.add_column(t, sa.Column("household_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    for t in HOUSEHOLD_ONLY:
        op.drop_column(t, "household_id")
    op.drop_column("plaid_items", "owner_user_id")
    op.drop_column("plaid_items", "household_id")
    for t in OWNER_VIS:
        op.drop_column(t, "visibility")
        op.drop_column(t, "owner_user_id")
        op.drop_column(t, "household_id")
