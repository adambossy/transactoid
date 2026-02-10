"""Add category provenance columns and category event history table.

Revision ID: 006_add_category_provenance
Revises: 005_add_item_id_to_plaid_transactions
Create Date: 2026-02-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_category_provenance"
down_revision: str | Sequence[str] | None = "005_add_item_id_to_plaid_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add provenance columns, event table, checks, and backfill."""
    op.add_column(
        "derived_transactions",
        sa.Column("category_model", sa.String(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("category_method", sa.String(), nullable=True),
    )
    op.add_column(
        "derived_transactions",
        sa.Column("category_assigned_at", sa.TIMESTAMP(), nullable=True),
    )

    op.create_check_constraint(
        "ck_derived_transactions_category_method",
        "derived_transactions",
        "category_method IS NULL OR category_method IN "
        "('llm', 'manual', 'taxonomy_migration')",
    )
    op.create_check_constraint(
        "ck_derived_transactions_category_provenance_consistency",
        "derived_transactions",
        "(category_id IS NULL AND category_method IS NULL "
        "AND category_assigned_at IS NULL) OR "
        "(category_id IS NOT NULL AND category_method IS NOT NULL "
        "AND category_assigned_at IS NOT NULL)",
    )

    op.create_table(
        "transaction_category_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("from_category_id", sa.Integer(), nullable=True),
        sa.Column("to_category_id", sa.Integer(), nullable=False),
        sa.Column("from_category_key", sa.String(), nullable=True),
        sa.Column("to_category_key", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_category_id"],
            ["categories.category_id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_category_id"],
            ["categories.category_id"],
        ),
        sa.CheckConstraint(
            "method IN ('llm', 'manual', 'taxonomy_migration')",
            name="ck_transaction_category_events_method",
        ),
    )

    op.create_index(
        "idx_derived_transactions_category_method",
        "derived_transactions",
        ["category_method"],
    )
    op.create_index(
        "idx_derived_transactions_category_assigned_at",
        "derived_transactions",
        ["category_assigned_at"],
    )
    op.create_index(
        "idx_tce_transaction_id_created_at",
        "transaction_category_events",
        ["transaction_id", "created_at"],
    )
    op.create_index(
        "idx_tce_created_at",
        "transaction_category_events",
        ["created_at"],
    )
    op.create_index(
        "idx_tce_method",
        "transaction_category_events",
        ["method"],
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE derived_transactions
            SET category_model = 'gpt-5.2',
                category_method = 'llm',
                category_assigned_at = COALESCE(
                    updated_at,
                    created_at,
                    CURRENT_TIMESTAMP
                )
            WHERE category_id IS NOT NULL
              AND category_model IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO transaction_category_events (
                transaction_id,
                from_category_id,
                to_category_id,
                from_category_key,
                to_category_key,
                method,
                model,
                reason,
                created_at
            )
            SELECT
                dt.transaction_id,
                NULL,
                dt.category_id,
                NULL,
                c.key,
                'llm',
                dt.category_model,
                'bootstrap_backfill',
                dt.category_assigned_at
            FROM derived_transactions dt
            JOIN categories c ON c.category_id = dt.category_id
            WHERE dt.category_id IS NOT NULL
              AND dt.category_model = 'gpt-5.2'
              AND dt.category_method = 'llm'
              AND NOT EXISTS (
                  SELECT 1
                  FROM transaction_category_events e
                  WHERE e.transaction_id = dt.transaction_id
              )
            """
        )
    )


def downgrade() -> None:
    """Drop provenance columns and history table."""
    op.drop_index("idx_tce_method", table_name="transaction_category_events")
    op.drop_index("idx_tce_created_at", table_name="transaction_category_events")
    op.drop_index(
        "idx_tce_transaction_id_created_at", table_name="transaction_category_events"
    )
    op.drop_table("transaction_category_events")

    op.drop_index(
        "idx_derived_transactions_category_assigned_at",
        table_name="derived_transactions",
    )
    op.drop_index(
        "idx_derived_transactions_category_method",
        table_name="derived_transactions",
    )
    op.drop_constraint(
        "ck_derived_transactions_category_provenance_consistency",
        "derived_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_derived_transactions_category_method",
        "derived_transactions",
        type_="check",
    )
    op.drop_column("derived_transactions", "category_assigned_at")
    op.drop_column("derived_transactions", "category_method")
    op.drop_column("derived_transactions", "category_model")
