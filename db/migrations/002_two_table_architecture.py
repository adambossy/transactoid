"""Two-table transaction architecture with Amazon splitting support

Revision ID: 002_two_table_architecture
Revises: 183c77cd21a4
Create Date: 2025-12-31

Refactor from single transactions table to two tables:
- plaid_transactions: Immutable source data from Plaid
- derived_transactions: Mutable, enriched transactions for queries

This enables Amazon transaction splitting (1 Plaid → N derived) and
preserves user edits during regeneration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_two_table_architecture"
down_revision: str | Sequence[str] | None = "183c77cd21a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create new two-table architecture."""

    # Create plaid_transactions table
    op.create_table(
        "plaid_transactions",
        sa.Column(
            "plaid_transaction_id", sa.Integer(), autoincrement=True, nullable=False
        ),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=True),
        sa.Column("institution", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("plaid_transaction_id"),
        sa.UniqueConstraint(
            "external_id", "source", name="uq_plaid_transactions_external_source"
        ),
    )

    # Create indexes on plaid_transactions
    op.create_index(
        "idx_plaid_transactions_external",
        "plaid_transactions",
        ["external_id", "source"],
    )
    op.create_index(
        "idx_plaid_transactions_posted", "plaid_transactions", ["posted_at"]
    )

    # Create derived_transactions table
    op.create_table(
        "derived_transactions",
        sa.Column("transaction_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plaid_transaction_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=True),
        sa.Column("merchant_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("(FALSE)"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
        sa.UniqueConstraint("external_id", name="uq_derived_transactions_external_id"),
        sa.ForeignKeyConstraint(
            ["plaid_transaction_id"],
            ["plaid_transactions.plaid_transaction_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.merchant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.category_id"],
        ),
    )

    # Create indexes on derived_transactions
    op.create_index(
        "idx_derived_transactions_plaid",
        "derived_transactions",
        ["plaid_transaction_id"],
    )
    op.create_index(
        "idx_derived_transactions_posted", "derived_transactions", ["posted_at"]
    )
    op.create_index(
        "idx_derived_transactions_category", "derived_transactions", ["category_id"]
    )

    # For SQLite: recreate transaction_tags with new FK
    # SQLite doesn't support ALTER TABLE DROP/ADD CONSTRAINT
    # We need to recreate the table with the new FK
    op.drop_table("transaction_tags")
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.tag_id"],
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )

    # Drop old transactions table and its indexes
    op.drop_index("idx_transactions_external_source", table_name="transactions")
    op.drop_index("idx_transactions_is_verified", table_name="transactions")
    op.drop_index("idx_transactions_category_id", table_name="transactions")
    op.drop_index("idx_transactions_merchant_id", table_name="transactions")
    op.drop_index("idx_transactions_posted_at", table_name="transactions")
    op.drop_table("transactions")


def downgrade() -> None:
    """Downgrade not supported - data would be lost.

    To revert: repopulate from Plaid instead.
    """
    raise NotImplementedError(
        "Downgrade not supported for two-table architecture migration. "
        "Repopulate from Plaid instead."
    )
