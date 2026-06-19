"""Add source_channel and counterparty columns to merchants

Revision ID: 006_add_merchant_metadata_columns
Revises: 005_seed_account_sign_conventions
Create Date: 2026-06-18

Adds two nullable columns to merchants, caching wrapper-descriptor metadata that
is otherwise only implicitly encoded in normalized_name (Tier 2 of the
individual-recategorization / merchant-normalization plan):

- source_channel (VARCHAR(50)): the channel a transaction arrived through —
  'direct' for ordinary merchants, or a wrapper channel like 'zelle' | 'venmo'
  | 'atm' | 'paypal' | 'stripe' | 'bambora' | ... Defaults conceptually to
  'direct' for non-wrapper merchants; left nullable so pre-existing rows are
  untouched until the normalizer repopulates them going forward.

- counterparty (VARCHAR(200)): the human counterparty behind a wrapper
  descriptor (e.g. 'Tania (XXX-4352)' or 'Rory Mabin'). NULL for direct
  merchants, where the merchant itself is the counterparty.

Both nullable; no CHECK constraints, so this migration is dialect-agnostic
(no SQLite/PostgreSQL split needed). The matching ORM columns live on the
Merchant model in models.py so SQLite's Base.metadata.create_all stays in sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_merchant_metadata_columns"
down_revision: str | Sequence[str] | None = "005_seed_account_sign_conventions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source_channel and counterparty columns to merchants."""
    op.add_column(
        "merchants",
        sa.Column("source_channel", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "merchants",
        sa.Column("counterparty", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Remove source_channel and counterparty columns from merchants."""
    op.drop_column("merchants", "counterparty")
    op.drop_column("merchants", "source_channel")
