"""Add tenant columns + RLS to the web conversation tables

Revision ID: 019_add_conversation_tenancy
Revises: 017_encrypt_plaid_access_tokens
Create Date: 2026-07-04

Phase 2 puts the *website* conversation store under the same tenancy guarantee
as the finance schema. The web tables live in a dedicated ``web`` schema on the
same Postgres server (see ``penny.api.persistence.engine``), so this revision —
part of the single epic migration ledger — reaches into ``web.*``:

- ``web.conversations`` gains ``household_id`` / ``owner_user_id`` (nullable
  here; the phase-3 cutover backfills and tightens them, mirroring the finance
  012→013→014 pattern) and ``session_mode`` (``individual``/``joint``, NOT NULL
  with an ``individual`` default so existing rows are valid).
- A ``tenant_isolation`` policy (USING **and** WITH CHECK) + ``FORCE ROW LEVEL
  SECURITY`` on ``web.conversations`` fences reads and writes by household +
  owner/joint, using the phase-1a ``app.current_household``/``app.current_user``
  GUCs the store now sets on the web connection.
- ``web.conversation_messages`` carries no tenant columns; its policy scopes it
  through its parent (``conversation_id IN (SELECT ... FROM web.conversations)``),
  which is itself RLS-filtered — one source of truth for the predicate.

SQLite dev/tests skip this entirely: the columns come from the model via
``create_all`` and the store's app-layer filter is the tenant layer there.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_add_conversation_tenancy"
down_revision: str | Sequence[str] | None = "017_encrypt_plaid_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONV = "web.conversations"
_MSGS = "web.conversation_messages"

# Same shape as the finance owner/visibility predicate, but visibility derives
# from session_mode: a joint thread is household-shared, an individual thread is
# owner-only (in a joint session app.current_user is the nil sentinel, matching
# no real owner, so only joint rows pass).
_CONV_PREDICATE = (
    "household_id = current_setting('app.current_household', true)::uuid "
    "AND (owner_user_id = current_setting('app.current_user', true)::uuid "
    "OR session_mode = 'joint')"
)
# Messages inherit their conversation's visibility: the subquery is itself
# filtered by the conversations policy.
_MSG_PREDICATE = f"conversation_id IN (SELECT conversation_id FROM {_CONV})"  # noqa: S608


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE SCHEMA IF NOT EXISTS web")
    op.execute(f"ALTER TABLE {_CONV} ADD COLUMN IF NOT EXISTS household_id uuid")
    op.execute(f"ALTER TABLE {_CONV} ADD COLUMN IF NOT EXISTS owner_user_id uuid")
    op.execute(
        f"ALTER TABLE {_CONV} ADD COLUMN IF NOT EXISTS session_mode "
        "varchar NOT NULL DEFAULT 'individual'"
    )
    for table, predicate in ((_CONV, _CONV_PREDICATE), (_MSGS, _MSG_PREDICATE)):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (_MSGS, _CONV):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_CONV} DROP COLUMN IF EXISTS session_mode")
    op.execute(f"ALTER TABLE {_CONV} DROP COLUMN IF EXISTS owner_user_id")
    op.execute(f"ALTER TABLE {_CONV} DROP COLUMN IF EXISTS household_id")
