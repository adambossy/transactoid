"""Add investments support columns

Revision ID: 006_add_investments_support
Revises: 005_add_item_id_to_plaid_transactions
Create Date: 2026-02-11

Adds columns for investments ingestion and reporting mode:
- plaid_items.investments_synced_through: Watermark for incremental investment sync
- derived_transactions.reporting_mode: Include/exclude flag for analytics
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_investments_support"
down_revision: str | Sequence[str] | None = "005_add_item_id_to_plaid_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add investments support columns."""
    # Add investments_synced_through to plaid_items
    op.add_column(
        "plaid_items",
        sa.Column("investments_synced_through", sa.Date(), nullable=True),
    )

    # Add reporting_mode to derived_transactions
    # NULL treated as DEFAULT_INCLUDE for backward compatibility
    op.add_column(
        "derived_transactions",
        sa.Column("reporting_mode", sa.String(), nullable=True),
    )

    # Add index for filtering by reporting_mode
    op.create_index(
        "idx_derived_transactions_reporting_mode",
        "derived_transactions",
        ["reporting_mode"],
    )


def downgrade() -> None:
    """Remove investments support columns."""
    op.drop_index(
        "idx_derived_transactions_reporting_mode", table_name="derived_transactions"
    )
    op.drop_column("derived_transactions", "reporting_mode")
    op.drop_column("plaid_items", "investments_synced_through")
