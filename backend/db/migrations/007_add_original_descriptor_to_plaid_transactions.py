"""Add original_descriptor to plaid_transactions

Revision ID: 007_add_original_descriptor_to_plaid_transactions
Revises: 006_add_merchant_metadata_columns
Create Date: 2026-06-19

Adds a nullable ``original_descriptor`` column to plaid_transactions to retain
Plaid's raw issuer description (their field is ``original_description``; named
with the ``_descriptor`` suffix here to match ``merchant_descriptor``).
``merchant_descriptor`` (= merchant_name or name) collapses wrapper merchants
like Venmo to a bare label and loses the counterparty; original_descriptor
keeps it — e.g. for a directly-linked Venmo item, "Jenny O'Leary :venmo_dollar:".

Nullable, no constraints: dialect-agnostic. The matching ORM column lives on the
PlaidTransaction model so SQLite's create_all stays in sync. Existing rows stay
NULL until a re-sync repopulates them (Plaid only supplies the field on a fresh
pull).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_add_original_descriptor_to_plaid_transactions"
down_revision: str | Sequence[str] | None = "006_add_merchant_metadata_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plaid_transactions",
        sa.Column("original_descriptor", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plaid_transactions", "original_descriptor")
