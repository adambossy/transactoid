"""Add refund linkage columns to derived_transactions

Revision ID: 003_add_refund_columns_to_derived_transactions
Revises: 002_add_email_receipts_and_pending_receipt_matches
Create Date: 2026-05-01

Adds three nullable columns to derived_transactions to support refund linkage:

- refund_of_transaction_id (INTEGER, FK → derived_transactions, ON DELETE SET NULL):
  self-referential FK pointing from a refund row to the original charge it offsets.
  If the original charge is deleted the refund row survives with this field NULLed
  (ON DELETE SET NULL) — auditable orphan rather than silent cascade loss.

- refund_matched_by (TEXT, CHECK IN ('user', 'auto')):
  Records who created the link. Currently only 'user' is set (via CLI);
  'auto' is reserved for the future email-receipt pipeline.

- refund_matched_at (TIMESTAMP):
  Wall-clock UTC time when the link was established.

A partial index on refund_of_transaction_id (WHERE NOT NULL) supports the
"find all refunds of transaction X" query efficiently.

NOTE: The CHECK constraint on refund_matched_by also lives in the ORM model's
__table_args__ (DerivedTransaction in models.py) so SQLite enforces it via the
ORM. PostgreSQL enforces it via the op.create_check_constraint call below.
If the allowed values change, update BOTH this migration AND the ORM.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_add_refund_columns_to_derived_transactions"
down_revision: str | Sequence[str] | None = (
    "002_add_email_receipts_and_pending_receipt_matches"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add refund_of_transaction_id, refund_matched_by, refund_matched_at columns."""
    op.add_column(
        "derived_transactions",
        sa.Column("refund_of_transaction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("refund_matched_by", sa.Text(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("refund_matched_at", sa.TIMESTAMP(), nullable=True),
    )

    bind = op.get_bind()

    # PostgreSQL supports self-FK via ALTER TABLE ADD CONSTRAINT.
    # SQLite does not support ALTER TABLE ADD CONSTRAINT, so the FK and CHECK
    # are enforced on SQLite via the ORM model's __table_args__ instead.
    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_derived_transactions_refund_of",
            "derived_transactions",
            "derived_transactions",
            ["refund_of_transaction_id"],
            ["transaction_id"],
            ondelete="SET NULL",
        )
        # IMPORTANT: if the allowed values change, update BOTH this constraint
        # AND the ORM model's __table_args__ CheckConstraint entry.
        op.create_check_constraint(
            "ck_derived_transactions_refund_matched_by",
            "derived_transactions",
            "refund_matched_by IS NULL OR refund_matched_by IN ('user', 'auto')",
        )
        # All-three-NULL or all-three-NOT-NULL: prevents partial refund link state.
        # IMPORTANT: also update the ORM model's __table_args__ if this changes.
        op.create_check_constraint(
            "ck_derived_transactions_refund_consistency",
            "derived_transactions",
            "(refund_of_transaction_id IS NULL "
            "AND refund_matched_by IS NULL "
            "AND refund_matched_at IS NULL) OR "
            "(refund_of_transaction_id IS NOT NULL "
            "AND refund_matched_by IS NOT NULL "
            "AND refund_matched_at IS NOT NULL)",
        )

    # Partial index: efficient lookup of all refunds for a given original.
    # SQLite supports partial indexes (WHERE clause); safe on both dialects.
    op.create_index(
        "idx_derived_transactions_refund_of_transaction_id",
        "derived_transactions",
        ["refund_of_transaction_id"],
        unique=False,
        postgresql_where=sa.text("refund_of_transaction_id IS NOT NULL"),
        sqlite_where=sa.text("refund_of_transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove refund columns and related constraints/indexes."""
    op.drop_index(
        "idx_derived_transactions_refund_of_transaction_id",
        table_name="derived_transactions",
    )

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "ck_derived_transactions_refund_consistency",
            "derived_transactions",
            type_="check",
        )
        op.drop_constraint(
            "ck_derived_transactions_refund_matched_by",
            "derived_transactions",
            type_="check",
        )
        op.drop_constraint(
            "fk_derived_transactions_refund_of",
            "derived_transactions",
            type_="foreignkey",
        )

    op.drop_column("derived_transactions", "refund_matched_at")
    op.drop_column("derived_transactions", "refund_matched_by")
    op.drop_column("derived_transactions", "refund_of_transaction_id")
