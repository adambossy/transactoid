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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    derived_columns = {
        column["name"] for column in inspector.get_columns("derived_transactions")
    }
    derived_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("derived_transactions")
        if constraint.get("name")
    }
    derived_indexes = {
        index["name"] for index in inspector.get_indexes("derived_transactions")
    }
    has_event_table = inspector.has_table("transaction_category_events")
    event_indexes: set[str] = set()
    if has_event_table:
        event_indexes = {
            name
            for index in inspector.get_indexes("transaction_category_events")
            if isinstance((name := index.get("name")), str)
        }

    if "category_model" not in derived_columns:
        op.add_column(
            "derived_transactions",
            sa.Column("category_model", sa.String(), nullable=True),
        )
    if "category_method" not in derived_columns:
        op.add_column(
            "derived_transactions",
            sa.Column("category_method", sa.String(), nullable=True),
        )
    if "category_assigned_at" not in derived_columns:
        op.add_column(
            "derived_transactions",
            sa.Column("category_assigned_at", sa.TIMESTAMP(), nullable=True),
        )

    conn = bind
    conn.execute(
        sa.text(
            """
            UPDATE derived_transactions
            SET category_model = NULL,
                category_method = NULL,
                category_assigned_at = NULL
            WHERE category_id IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE derived_transactions
            SET category_model = COALESCE(category_model, 'gpt-5.2'),
                category_method = CASE
                    WHEN category_method IN ('llm', 'manual', 'taxonomy_migration')
                        THEN category_method
                    ELSE 'llm'
                END,
                category_assigned_at = COALESCE(
                    category_assigned_at,
                    updated_at,
                    created_at,
                    CURRENT_TIMESTAMP
                )
            WHERE category_id IS NOT NULL
            """
        )
    )

    if "ck_derived_transactions_category_method" not in derived_checks:
        op.create_check_constraint(
            "ck_derived_transactions_category_method",
            "derived_transactions",
            "category_method IS NULL OR category_method IN "
            "('llm', 'manual', 'taxonomy_migration')",
        )
    if "ck_derived_transactions_category_provenance_consistency" not in derived_checks:
        op.create_check_constraint(
            "ck_derived_transactions_category_provenance_consistency",
            "derived_transactions",
            "(category_id IS NULL AND category_method IS NULL "
            "AND category_assigned_at IS NULL) OR "
            "(category_id IS NOT NULL AND category_method IS NOT NULL "
            "AND category_assigned_at IS NOT NULL)",
        )

    if not has_event_table:
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

    if "idx_derived_transactions_category_method" not in derived_indexes:
        op.create_index(
            "idx_derived_transactions_category_method",
            "derived_transactions",
            ["category_method"],
        )
    if "idx_derived_transactions_category_assigned_at" not in derived_indexes:
        op.create_index(
            "idx_derived_transactions_category_assigned_at",
            "derived_transactions",
            ["category_assigned_at"],
        )

    if not has_event_table:
        event_indexes = set()
    if "idx_tce_transaction_id_created_at" not in event_indexes:
        op.create_index(
            "idx_tce_transaction_id_created_at",
            "transaction_category_events",
            ["transaction_id", "created_at"],
        )
    if "idx_tce_created_at" not in event_indexes:
        op.create_index(
            "idx_tce_created_at",
            "transaction_category_events",
            ["created_at"],
        )
    if "idx_tce_method" not in event_indexes:
        op.create_index(
            "idx_tce_method",
            "transaction_category_events",
            ["method"],
        )

    conn.execute(
        sa.text(
            """
            UPDATE derived_transactions
            SET category_model = COALESCE(category_model, 'gpt-5.2'),
                category_method = COALESCE(category_method, 'llm'),
                category_assigned_at = COALESCE(
                    category_assigned_at,
                    updated_at,
                    created_at,
                    CURRENT_TIMESTAMP
                )
            WHERE category_id IS NOT NULL
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    has_event_table = inspector.has_table("transaction_category_events")
    event_indexes: set[str] = set()
    if has_event_table:
        event_indexes = {
            name
            for index in inspector.get_indexes("transaction_category_events")
            if isinstance((name := index.get("name")), str)
        }
    derived_columns = {
        column["name"] for column in inspector.get_columns("derived_transactions")
    }
    derived_indexes = {
        index["name"] for index in inspector.get_indexes("derived_transactions")
    }
    derived_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("derived_transactions")
        if constraint.get("name")
    }

    if "idx_tce_method" in event_indexes:
        op.drop_index("idx_tce_method", table_name="transaction_category_events")
    if "idx_tce_created_at" in event_indexes:
        op.drop_index("idx_tce_created_at", table_name="transaction_category_events")
    if "idx_tce_transaction_id_created_at" in event_indexes:
        op.drop_index(
            "idx_tce_transaction_id_created_at",
            table_name="transaction_category_events",
        )
    if has_event_table:
        op.drop_table("transaction_category_events")

    if "idx_derived_transactions_category_assigned_at" in derived_indexes:
        op.drop_index(
            "idx_derived_transactions_category_assigned_at",
            table_name="derived_transactions",
        )
    if "idx_derived_transactions_category_method" in derived_indexes:
        op.drop_index(
            "idx_derived_transactions_category_method",
            table_name="derived_transactions",
        )
    if "ck_derived_transactions_category_provenance_consistency" in derived_checks:
        op.drop_constraint(
            "ck_derived_transactions_category_provenance_consistency",
            "derived_transactions",
            type_="check",
        )
    if "ck_derived_transactions_category_method" in derived_checks:
        op.drop_constraint(
            "ck_derived_transactions_category_method",
            "derived_transactions",
            type_="check",
        )
    if "category_assigned_at" in derived_columns:
        op.drop_column("derived_transactions", "category_assigned_at")
    if "category_method" in derived_columns:
        op.drop_column("derived_transactions", "category_method")
    if "category_model" in derived_columns:
        op.drop_column("derived_transactions", "category_model")
