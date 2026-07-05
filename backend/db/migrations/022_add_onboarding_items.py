"""Add the web ``onboarding_items`` table with owner-scoped RLS

Revision ID: 022_add_onboarding_items
Revises: 021_add_usage_events_and_user_billing
Create Date: 2026-07-04

Phase 5: per-user progressive-onboarding state. Website/app state, so — like the
phase-2/2b web tables — it lives in the dedicated ``web`` schema (out of the
agent ``run_sql`` blast radius) and is create_all-managed; this revision layers
the RLS on top.

Owner-scoped within a household (decision D3): an item is private to its
``owner_user_id`` (a spouse never sees the other's onboarding), so
``tenant_isolation`` keys on ``household_id`` **and** ``owner_user_id`` against
the ``app.current_household`` / ``app.current_user`` GUCs the owner-scoped web
session binds. USING **and** WITH CHECK + FORCE fence reads and writes.

SQLite dev/tests skip this entirely: the table comes from the model via
``create_all`` and the store's ``household_id`` + ``owner_user_id`` filter is the
tenant layer there.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "022_add_onboarding_items"
down_revision: str | Sequence[str] | None = "021_add_usage_events_and_user_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "web.onboarding_items"
_PREDICATE = (
    "household_id = current_setting('app.current_household', true)::uuid "
    "AND owner_user_id = current_setting('app.current_user', true)::uuid"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE SCHEMA IF NOT EXISTS web")
    # Defensive create (create_all normally owns web-table creation): keep the
    # pure-migration path working without depending on startup ordering.
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id uuid PRIMARY KEY,
            household_id uuid NOT NULL,
            owner_user_id uuid NOT NULL,
            item_key varchar NOT NULL,
            status varchar NOT NULL DEFAULT 'pending',
            trigger_state json NOT NULL DEFAULT '{{}}',
            created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_onboarding_items_owner_item UNIQUE (owner_user_id, item_key),
            CONSTRAINT ck_onboarding_items_status
                CHECK (status IN ('pending', 'accepted', 'dismissed'))
        )
        """
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_TABLE} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
