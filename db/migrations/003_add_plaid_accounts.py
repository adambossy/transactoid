"""Add plaid_accounts table and sync_cursor column

Revision ID: 003_add_plaid_accounts
Revises: 002_two_table_architecture
Create Date: 2026-01-07

Adds the plaid_accounts table to store account metadata from Plaid.
This enables detecting duplicate items (same accounts linked multiple times)
and provides account information for transaction display.

Also adds sync_cursor column to plaid_items for incremental sync support.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_add_plaid_accounts"
down_revision: str | Sequence[str] | None = "002_two_table_architecture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add plaid_accounts table and sync_cursor column."""
    # Add sync_cursor column to plaid_items (if not already present)
    # Check if the column exists first
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'plaid_items' AND column_name = 'sync_cursor'"
        )
    )
    if result.fetchone() is None:
        op.add_column(
            "plaid_items",
            sa.Column("sync_cursor", sa.Text(), nullable=True),
        )

    # Create plaid_accounts table
    op.create_table(
        "plaid_accounts",
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("mask", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("subtype", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("official_name", sa.String(), nullable=True),
        sa.Column("institution_id", sa.String(), nullable=True),
        sa.Column("institution_name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("account_id"),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["plaid_items.item_id"],
            ondelete="CASCADE",
        ),
    )

    # Create index for looking up accounts by item
    op.create_index(
        "idx_plaid_accounts_item_id",
        "plaid_accounts",
        ["item_id"],
    )


def downgrade() -> None:
    """Remove plaid_accounts table and sync_cursor column."""
    op.drop_index("idx_plaid_accounts_item_id", table_name="plaid_accounts")
    op.drop_table("plaid_accounts")
    op.drop_column("plaid_items", "sync_cursor")
