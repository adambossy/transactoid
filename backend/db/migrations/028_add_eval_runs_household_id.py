"""Add household_id to eval_runs (per-household watermark)

Revision ID: 028_add_eval_runs_household_id
Revises: 027_eval_runs_allow_failed_status
Create Date: 2026-07-18

The eval cohort is scoped to one household, so the resume watermark must be too:
a completed run for household A must not gate household B's cohort. Add a nullable
``household_id`` the eval stamps on each run and filters ``last_eval_watermark`` by.
Nullable (no backfill): eval infra, not an RLS/tenant column — the seed row and
any legacy rows may leave it unset, which simply matches no household filter.

``eval_runs`` is a finance-``Base`` table, so this runs on BOTH dialects (SQLite
dev/tests build the same column via ``create_all``; the drift guard compares them).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028_add_eval_runs_household_id"
down_revision: str | Sequence[str] | None = "027_eval_runs_allow_failed_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("household_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_runs", "household_id")
