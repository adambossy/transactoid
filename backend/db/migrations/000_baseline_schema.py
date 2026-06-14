"""Baseline schema (root of the penny migration chain)

Revision ID: 000_baseline_schema
Revises: None (root)
Create Date: 2026-06-14

Creates the pre-001 penny schema: the 11 baseline tables that previously
existed only via ``Base.metadata.create_all`` (``DB.create_schema``). With this
migration at the root of the chain, ``alembic upgrade head`` builds the schema
from empty (baseline + 001..005) and reproduces exactly what ``create_all``
produces.

This migration deliberately STOPS at the pre-001 column/table set. Everything
added by later migrations is excluded so they still apply cleanly on top:

- transaction_items table + derived_transactions split columns  -> 001
- email_receipts, pending_receipt_matches tables                -> 002
- derived_transactions refund columns                           -> 003
- account_sign_conventions table                                -> 004

Only the two always-present CHECK constraints on derived_transactions
(category_method, category provenance consistency) are emitted here, inside
CREATE TABLE so they apply on all dialects. The split_source / refund CHECKs
belong to 001 / 003 (PostgreSQL only; SQLite enforces them via the ORM).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000_baseline_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the 11 baseline tables in FK-dependency order."""
    op.create_table(
        "merchants",
        sa.Column("merchant_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("merchant_id"),
        sa.UniqueConstraint("normalized_name"),
    )

    op.create_table(
        "categories",
        sa.Column("category_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rules", sa.Text(), nullable=True),
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
        sa.Column("deprecated_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.category_id"]),
        sa.PrimaryKeyConstraint("category_id"),
    )
    # Partial unique index: only one active (non-deprecated) row per key.
    op.create_index(
        "uq_categories_key_active",
        "categories",
        ["key"],
        unique=True,
        postgresql_where=sa.text("deprecated_at IS NULL"),
        sqlite_where=sa.text("deprecated_at IS NULL"),
    )

    op.create_table(
        "plaid_items",
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("institution_id", sa.String(), nullable=True),
        sa.Column("institution_name", sa.String(), nullable=True),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("investments_synced_through", sa.Date(), nullable=True),
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
        sa.PrimaryKeyConstraint("item_id"),
    )

    op.create_table(
        "plaid_transactions",
        sa.Column(
            "plaid_transaction_id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=True),
        sa.Column("institution", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["item_id"], ["plaid_items.item_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plaid_transaction_id"),
        sa.UniqueConstraint(
            "external_id", "source", name="uq_plaid_transactions_external_source"
        ),
    )

    op.create_table(
        "derived_transactions",
        sa.Column("transaction_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plaid_transaction_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("posted_at", sa.Date(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=True),
        sa.Column("merchant_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("category_model", sa.String(), nullable=True),
        sa.Column("category_method", sa.String(), nullable=True),
        sa.Column("category_assigned_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("web_search_summary", sa.Text(), nullable=True),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column("reporting_mode", sa.String(), nullable=True),
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
        # Always-present CHECKs, emitted inside CREATE TABLE so they apply on all
        # dialects (including SQLite). The split_source / refund CHECKs are added
        # later by 001 / 003 and are intentionally NOT here.
        sa.CheckConstraint(
            "category_method IS NULL OR category_method IN "
            "('llm', 'manual', 'taxonomy_migration')",
            name="ck_derived_transactions_category_method",
        ),
        sa.CheckConstraint(
            "(category_id IS NULL AND category_method IS NULL "
            "AND category_assigned_at IS NULL) OR "
            "(category_id IS NOT NULL AND category_method IS NOT NULL "
            "AND category_assigned_at IS NOT NULL)",
            name="ck_derived_transactions_category_provenance_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["plaid_transaction_id"],
            ["plaid_transactions.plaid_transaction_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.merchant_id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.category_id"]),
        sa.PrimaryKeyConstraint("transaction_id"),
        sa.UniqueConstraint("external_id"),
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
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('llm', 'manual', 'taxonomy_migration')",
            name="ck_transaction_category_events_method",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["from_category_id"], ["categories.category_id"]),
        sa.ForeignKeyConstraint(["to_category_id"], ["categories.category_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )

    op.create_table(
        "tags",
        sa.Column("tag_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("tag_id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["derived_transactions.transaction_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.tag_id"]),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )

    op.create_table(
        "amazon_login_profiles",
        sa.Column("profile_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("browserbase_context_id", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("last_auth_at", sa.DateTime(), nullable=True),
        sa.Column("last_auth_status", sa.String(length=32), nullable=True),
        sa.Column("last_auth_error", sa.Text(), nullable=True),
        sa.Column("history_complete_through", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint("profile_key"),
    )

    op.create_table(
        "amazon_orders",
        sa.Column("order_id", sa.String(length=50), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("order_total_cents", sa.Integer(), nullable=False),
        sa.Column(
            "tax_cents", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "shipping_cents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["amazon_login_profiles.profile_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index(
        "ix_amazon_orders_profile_id", "amazon_orders", ["profile_id"], unique=False
    )

    op.create_table(
        "amazon_items",
        sa.Column("item_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.String(length=50), nullable=False),
        sa.Column("asin", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "quantity", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
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
        sa.ForeignKeyConstraint(["order_id"], ["amazon_orders.order_id"]),
        sa.PrimaryKeyConstraint("item_id"),
        sa.UniqueConstraint("order_id", "asin", name="uq_amazon_item_order_asin"),
    )


def downgrade() -> None:
    """Drop the baseline tables in reverse FK-dependency order."""
    op.drop_table("amazon_items")
    op.drop_index("ix_amazon_orders_profile_id", table_name="amazon_orders")
    op.drop_table("amazon_orders")
    op.drop_table("amazon_login_profiles")
    op.drop_table("transaction_tags")
    op.drop_table("tags")
    op.drop_table("transaction_category_events")
    op.drop_table("derived_transactions")
    op.drop_table("plaid_transactions")
    op.drop_index("uq_categories_key_active", table_name="categories")
    op.drop_table("categories")
    op.drop_table("plaid_items")
    op.drop_table("merchants")
