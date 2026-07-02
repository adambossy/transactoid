"""Add Plaid raw name + enrichment columns to plaid_transactions

Revision ID: 009_add_plaid_raw_name_and_enrichment
Revises: 008_merge_heads
Create Date: 2026-07-01

Plaid returns a fuller raw ``name`` (e.g. "AplPay MY FAVORITE CBROOKLYN") that we
previously discarded — we only kept the cleaned ``merchant_name`` as
``merchant_descriptor``. The raw name carries location / payment-rail detail that
helps categorization when the cleaned name is bare or truncated, so we now
persist it (and surface it to the categorizer).

We also persist two Plaid enrichment blobs for later analysis — ``counterparties``
and ``personal_finance_category`` (Plaid's own category guess). These are stored
verbatim and are deliberately NOT surfaced to the categorizer agent.

``original_description`` (added in 007) stays as-is; Plaid does not populate it in
practice, so ``raw_name`` is the field that actually carries the extra signal.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_add_plaid_raw_name_and_enrichment"
down_revision: str | Sequence[str] | None = "008_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add raw_name, counterparties, and personal_finance_category columns."""
    op.add_column("plaid_transactions", sa.Column("raw_name", sa.Text(), nullable=True))
    op.add_column(
        "plaid_transactions", sa.Column("counterparties", sa.JSON(), nullable=True)
    )
    op.add_column(
        "plaid_transactions",
        sa.Column("personal_finance_category", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Drop the three columns."""
    op.drop_column("plaid_transactions", "personal_finance_category")
    op.drop_column("plaid_transactions", "counterparties")
    op.drop_column("plaid_transactions", "raw_name")
