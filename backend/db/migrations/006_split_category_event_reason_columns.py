"""Split transaction_category_events.reason into two purpose-specific columns

Revision ID: 006_split_category_event_reason_columns
Revises: 005_seed_account_sign_conventions
Create Date: 2026-06-14

The append-only ``transaction_category_events`` table had a single free-text
``reason`` column that conflated two different things: why a category was
originally CHOSEN by the LLM, and why it was later CHANGED by a user/migration.

This migration splits them:

- ``reason`` is renamed to ``recategorization_reason`` — the natural-language
  reason a category CHANGED (manual recats + taxonomy migrations). The legacy
  fixed-string values (``'sync_categorize'``, ``'recategorize_merchant'``, …)
  are carried over unchanged by the rename; they are not nulled out.
- a new nullable ``categorization_reasoning`` column is added — the LLM/agent's
  rationale for an original ``method='llm'`` categorization decision.

``DB._insert_category_event`` routes its ``reason`` argument to the matching
column based on ``method`` (llm -> categorization_reasoning; manual /
taxonomy_migration -> recategorization_reason).

Uses ``batch_alter_table`` so the rename also works on SQLite (which has no
native ALTER COLUMN RENAME on older versions and recreates the table instead).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_split_category_event_reason_columns"
down_revision: str | Sequence[str] | None = "005_seed_account_sign_conventions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename reason -> recategorization_reason and add categorization_reasoning."""
    with op.batch_alter_table("transaction_category_events") as batch_op:
        batch_op.alter_column(
            "reason",
            new_column_name="recategorization_reason",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
        batch_op.add_column(
            sa.Column("categorization_reasoning", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Reverse: drop categorization_reasoning and rename column back to reason."""
    with op.batch_alter_table("transaction_category_events") as batch_op:
        batch_op.drop_column("categorization_reasoning")
        batch_op.alter_column(
            "recategorization_reason",
            new_column_name="reason",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
