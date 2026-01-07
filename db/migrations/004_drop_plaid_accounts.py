"""Drop plaid_accounts table - switch to live API fetching

Revision ID: 004_drop_plaid_accounts
Revises: 003_add_plaid_accounts
Create Date: 2026-01-07

The plaid_accounts table was never populated during normal operations.
Account deduplication now uses live Plaid API fetching instead of
storing account metadata locally.

Note: sync_cursor column on plaid_items is retained for incremental sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_drop_plaid_accounts"
down_revision: str | Sequence[str] | None = "003_add_plaid_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop plaid_accounts table."""
    op.drop_index("idx_plaid_accounts_item_id", table_name="plaid_accounts")
    op.drop_table("plaid_accounts")


def downgrade() -> None:
    """Recreate plaid_accounts table."""
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
    op.create_index(
        "idx_plaid_accounts_item_id",
        "plaid_accounts",
        ["item_id"],
    )
