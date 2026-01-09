"""Add item_id foreign key to plaid_transactions for cascade delete

Revision ID: 005_add_item_id_to_plaid_transactions
Revises: 004_drop_plaid_accounts
Create Date: 2026-01-08

Adds item_id column to plaid_transactions with ON DELETE CASCADE to plaid_items.
This enables cascade delete: plaid_items -> plaid_transactions -> derived_transactions.

The column is nullable to allow backfilling existing data via a separate script.
After backfill, consider adding a NOT NULL constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_add_item_id_to_plaid_transactions"
down_revision: str | Sequence[str] | None = "004_drop_plaid_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add item_id column with FK to plaid_items."""
    # Add item_id column (nullable for backfill)
    op.add_column(
        "plaid_transactions",
        sa.Column("item_id", sa.String(), nullable=True),
    )

    # Add foreign key constraint with CASCADE delete
    op.create_foreign_key(
        "fk_plaid_transactions_item_id",
        "plaid_transactions",
        "plaid_items",
        ["item_id"],
        ["item_id"],
        ondelete="CASCADE",
    )

    # Add index for performance
    op.create_index(
        "idx_plaid_transactions_item_id",
        "plaid_transactions",
        ["item_id"],
    )


def downgrade() -> None:
    """Remove item_id column and FK."""
    op.drop_index("idx_plaid_transactions_item_id", table_name="plaid_transactions")
    op.drop_constraint(
        "fk_plaid_transactions_item_id", "plaid_transactions", type_="foreignkey"
    )
    op.drop_column("plaid_transactions", "item_id")
