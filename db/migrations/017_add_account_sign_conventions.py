"""Add account_sign_conventions table

Revision ID: 017_add_account_sign_conventions
Revises: 016_add_refund_columns_to_derived_transactions
Create Date: 2026-05-01

Adds the account_sign_conventions lookup table. Each row records whether
a given Plaid account reports expenses as positive ('expense_positive') or
negative ('expense_negative') amounts.

account_id matches plaid_transactions.account_id (TEXT). There is no
foreign-key because the plaid_accounts table was dropped in migration 004.

sign_convention and provenance CHECK constraints are defined inside the
CREATE TABLE call, so they are emitted on all dialects (including SQLite)
without a dialect guard. No separate op.create_check_constraint is needed.

NOTE: The values allowed by the CHECK constraints must match the
__table_args__ CheckConstraints in the AccountSignConvention ORM model.
If the allowed values change, update BOTH this migration AND the model.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017_add_account_sign_conventions"
down_revision: str | Sequence[str] | None = (
    "016_add_refund_columns_to_derived_transactions"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create account_sign_conventions table."""
    op.create_table(
        "account_sign_conventions",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("sign_convention", sa.Text(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # CHECK constraints inside CREATE TABLE run on all dialects (SQLite + PG).
        # NOTE: values must match the ORM model's __table_args__ CheckConstraints.
        sa.CheckConstraint(
            "sign_convention IN ('expense_positive', 'expense_negative')",
            name="ck_account_sign_conventions_sign_convention",
        ),
        sa.CheckConstraint(
            "provenance IN ('seeded', 'manual')",
            name="ck_account_sign_conventions_provenance",
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    """Drop account_sign_conventions table."""
    op.drop_table("account_sign_conventions")
