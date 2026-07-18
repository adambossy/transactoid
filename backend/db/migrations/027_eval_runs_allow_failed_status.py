"""Allow status='failed' on eval_runs

Revision ID: 027_eval_runs_allow_failed_status
Revises: 027_tags_unique_per_household
Create Date: 2026-07-16

The eval now records a durable ``status='failed'`` row when a run raises, so a
crash leaves a trace in the eval history (and the watermark does not advance, so
the cohort is retried). Extend ``ck_eval_runs_status`` to accept ``'failed'``.

Postgres-only: SQLite dev/tests build the constraint from the model via
``create_all``. A CHECK change is DROP + ADD on Postgres.

Rechained after the fact: this and ``027_tags_unique_per_household`` both landed
off ``026`` on separate branches, leaving two alembic heads that broke
``penny migrate`` (multiple head revisions). Neither had been applied to prod,
so linearizing 026 → 027_tags → this → 028 was safe.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "027_eval_runs_allow_failed_status"
down_revision: str | Sequence[str] | None = "027_tags_unique_per_household"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_eval_runs_status"
_OLD = "status IN ('completed', 'skipped_empty', 'skipped_incomplete_baseline')"
_NEW = (
    "status IN ('completed', 'skipped_empty', 'skipped_incomplete_baseline', 'failed')"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE eval_runs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"ALTER TABLE eval_runs ADD CONSTRAINT {_CONSTRAINT} CHECK ({_NEW})")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE eval_runs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"ALTER TABLE eval_runs ADD CONSTRAINT {_CONSTRAINT} CHECK ({_OLD})")
