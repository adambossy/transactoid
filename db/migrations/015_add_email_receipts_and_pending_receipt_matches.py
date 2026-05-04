"""Add email_receipts and pending_receipt_matches tables

Revision ID: 015_add_email_receipts_and_pending_receipt_matches
Revises: 014_add_transaction_items_and_split_columns
Create Date: 2026-05-01

Creates two sidecar tables for the email-receipt matching pipeline:

- email_receipts: dedup + audit table for parsed Gmail messages.
  message_id is the dedup key (UNIQUE). subject/sender are captured for
  diagnostics and allowlist matching only — never written to logs or cache.

- pending_receipt_matches: low-confidence email-to-transaction candidates
  queued for human review in the web UI. Items are NOT written to
  transaction_items until a candidate is status='confirmed'.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_add_email_receipts_and_pending_receipt_matches"
down_revision: str | Sequence[str] | None = (
    "014_add_transaction_items_and_split_columns"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create email_receipts and pending_receipt_matches tables."""
    op.create_table(
        "email_receipts",
        sa.Column("receipt_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(2048), nullable=True),
        sa.Column("sender", sa.String(2048), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint("message_id", name="uq_email_receipts_message_id"),
    )
    op.create_index(
        "idx_email_receipts_received_at",
        "email_receipts",
        ["received_at"],
        unique=False,
    )

    op.create_table(
        "pending_receipt_matches",
        sa.Column("pending_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("candidate_txn_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("date_lag_days", sa.Integer(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        # This CHECK is emitted inside CREATE TABLE, so it runs on all dialects
        # including SQLite — no dialect guard needed here.
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="ck_pending_receipt_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["email_receipts.message_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_txn_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pending_id"),
        sa.UniqueConstraint(
            "message_id",
            "candidate_txn_id",
            name="uq_pending_receipt_matches_message_candidate",
        ),
    )
    op.create_index(
        "idx_pending_receipt_matches_status_created_at",
        "pending_receipt_matches",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_pending_receipt_matches_candidate_txn_id",
        "pending_receipt_matches",
        ["candidate_txn_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop pending_receipt_matches then email_receipts (FK order)."""
    op.drop_index(
        "idx_pending_receipt_matches_candidate_txn_id",
        table_name="pending_receipt_matches",
    )
    op.drop_index(
        "idx_pending_receipt_matches_status_created_at",
        table_name="pending_receipt_matches",
    )
    op.drop_table("pending_receipt_matches")

    op.drop_index("idx_email_receipts_received_at", table_name="email_receipts")
    op.drop_table("email_receipts")
