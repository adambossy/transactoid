"""Add the categorizer eval store (eval_runs + eval_items)

Revision ID: 007_add_eval_store
Revises: 006_split_category_event_reason_columns
Create Date: 2026-06-27

Eval infrastructure for the daily categorizer evaluation pipeline. These tables
are a separate concern from the product tables but live in the same durable DB so
the accuracy trend survives the disposable per-run Neon branch.

- ``eval_runs`` — one row per 12-hour eval run: the cohort size, the high-water
  mark the next run resumes from (``cohort_max_created_at``), the R2 fixture URL,
  the run status, and the version stamp (model / prompt / harness SHA / taxonomy /
  rules versions).
- ``eval_items`` — one row per cohort transaction: the legacy baseline and the
  agent's pick, the agent's reasoning/confidence, whether the fast path fired, and
  a best-effort Langfuse trace link. No verdict column — right/wrong is derived
  later from the corrections in ``transaction_category_events``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_add_eval_store"
down_revision: str | Sequence[str] | None = "006_split_category_event_reason_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create eval_runs and eval_items."""
    op.create_table(
        "eval_runs",
        sa.Column("eval_run_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "cohort_size", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("cohort_max_created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("branch_name", sa.String(), nullable=True),
        sa.Column("r2_fixture_url", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("harness_sha", sa.String(), nullable=True),
        sa.Column("taxonomy_version", sa.String(), nullable=True),
        sa.Column("rules_version", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'skipped_empty', 'skipped_incomplete_baseline')",
            name="ck_eval_runs_status",
        ),
        sa.PrimaryKeyConstraint("eval_run_id"),
    )
    op.create_table(
        "eval_items",
        sa.Column("eval_run_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=True),
        sa.Column("legacy_key", sa.String(), nullable=True),
        sa.Column("agent_key", sa.String(), nullable=True),
        sa.Column("agent_reasoning", sa.Text(), nullable=True),
        sa.Column("agent_confidence", sa.Float(), nullable=True),
        sa.Column("method_at_eval_time", sa.String(), nullable=False),
        sa.Column("trace_link", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method_at_eval_time IN ('fast_path', 'agent')",
            name="ck_eval_items_method_at_eval_time",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"], ["eval_runs.eval_run_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("eval_run_id", "transaction_id"),
    )
    op.create_index("idx_eval_items_transaction_id", "eval_items", ["transaction_id"])


def downgrade() -> None:
    """Drop the eval store."""
    op.drop_index("idx_eval_items_transaction_id", table_name="eval_items")
    op.drop_table("eval_items")
    op.drop_table("eval_runs")
