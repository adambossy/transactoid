"""Add transaction_items table and split provenance columns to derived_transactions

Revision ID: 014_add_transaction_items_and_split_columns
Revises: 013_partial_unique_category_key
Create Date: 2026-05-01

Creates the transaction_items table for generalised itemization (Amazon and
email receipts) and adds three nullable split-provenance columns to
derived_transactions so the origin of a split row can be traced back.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_add_transaction_items_and_split_columns"
down_revision: str | Sequence[str] | None = "013_partial_unique_category_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create transaction_items and add split columns to derived_transactions."""
    op.create_table(
        "transaction_items",
        sa.Column("item_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("itemization_source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        # This CHECK is emitted inside CREATE TABLE, so it runs on all dialects
        # including SQLite — no dialect guard needed here.
        sa.CheckConstraint(
            "itemization_source IN ('amazon_scrape', 'email_receipt', 'manual')",
            name="ck_transaction_items_itemization_source",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index(
        "idx_transaction_items_transaction_id",
        "transaction_items",
        ["transaction_id"],
        unique=False,
    )

    op.add_column(
        "derived_transactions",
        sa.Column("split_group_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("split_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("split_index", sa.Integer(), nullable=True),
    )

    # SQLite does not support ALTER TABLE ADD CONSTRAINT, so this guard skips the
    # explicit constraint on SQLite. On SQLite the allowed values are enforced by
    # the ORM __table_args__ CheckConstraint on DerivedTransaction instead.
    # IMPORTANT: if the allowed values change, update BOTH this migration's
    # op.create_check_constraint call AND the ORM model's __table_args__ entry.
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_derived_transactions_split_source",
            "derived_transactions",
            "split_source IS NULL OR split_source IN "
            "('user_split', 'amazon_mutation', 'email_mutation')",
        )


def downgrade() -> None:
    """Drop transaction_items and remove split columns from derived_transactions."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "ck_derived_transactions_split_source",
            "derived_transactions",
            type_="check",
        )
    op.drop_column("derived_transactions", "split_index")
    op.drop_column("derived_transactions", "split_source")
    op.drop_column("derived_transactions", "split_group_id")

    op.drop_index(
        "idx_transaction_items_transaction_id", table_name="transaction_items"
    )
    op.drop_table("transaction_items")
