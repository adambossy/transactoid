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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("plaid_transactions")
    }
    existing_foreign_keys = {
        fk["name"]
        for fk in inspector.get_foreign_keys("plaid_transactions")
        if fk.get("name")
    }
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("plaid_transactions")
    }

    # Support partially applied schemas by only creating missing objects.
    if "item_id" not in existing_columns:
        op.add_column(
            "plaid_transactions",
            sa.Column("item_id", sa.String(), nullable=True),
        )

    if "fk_plaid_transactions_item_id" not in existing_foreign_keys:
        op.create_foreign_key(
            "fk_plaid_transactions_item_id",
            "plaid_transactions",
            "plaid_items",
            ["item_id"],
            ["item_id"],
            ondelete="CASCADE",
        )

    if "idx_plaid_transactions_item_id" not in existing_indexes:
        op.create_index(
            "idx_plaid_transactions_item_id",
            "plaid_transactions",
            ["item_id"],
        )


def downgrade() -> None:
    """Remove item_id column and FK."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("plaid_transactions")
    }
    existing_foreign_keys = {
        fk["name"]
        for fk in inspector.get_foreign_keys("plaid_transactions")
        if fk.get("name")
    }
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("plaid_transactions")
    }

    if "idx_plaid_transactions_item_id" in existing_indexes:
        op.drop_index("idx_plaid_transactions_item_id", table_name="plaid_transactions")

    if "fk_plaid_transactions_item_id" in existing_foreign_keys:
        op.drop_constraint(
            "fk_plaid_transactions_item_id", "plaid_transactions", type_="foreignkey"
        )

    if "item_id" in existing_columns:
        op.drop_column("plaid_transactions", "item_id")
