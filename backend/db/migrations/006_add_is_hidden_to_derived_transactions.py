"""Add is_hidden flag to derived_transactions

Revision ID: 006_add_is_hidden_to_derived_transactions
Revises: 005_seed_account_sign_conventions
Create Date: 2026-06-21

Adds a single boolean column to derived_transactions:

- is_hidden (BOOLEAN, NOT NULL, DEFAULT FALSE):
  User-controlled flag marking rows the user has chosen to exclude from
  spending analysis. Toggled via the hide_transactions / unhide_transactions
  agent tools and excluded by default in the agent's query filters.

The server default of FALSE backfills existing rows on both SQLite and
PostgreSQL, so no separate data migration is needed. The same NOT NULL DEFAULT
FALSE definition lives in the ORM model (DerivedTransaction in models.py), so
dev/SQLite gets the column via Base.metadata.create_all and this migration
keeps Neon/Postgres in sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_is_hidden_to_derived_transactions"
down_revision: str | Sequence[str] | None = "005_seed_account_sign_conventions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the is_hidden column with a FALSE server default."""
    op.add_column(
        "derived_transactions",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    """Remove the is_hidden column."""
    op.drop_column("derived_transactions", "is_hidden")
