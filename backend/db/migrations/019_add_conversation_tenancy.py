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

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_add_conversation_tenancy"
down_revision: str | Sequence[str] | None = "018_add_workspace_store"
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

    # Create the base web.* tables if absent. On a fresh, alembic-only Postgres
    # DB nothing has made them yet (create_all is forbidden there), so the chain
    # must — otherwise the ALTERs below fail with "relation does not exist".
    # Idempotent: existing prod tables (originally from WebBase.create_all) are
    # left untouched. Columns mirror the models MINUS the tenant columns this
    # revision adds (household_id/owner_user_id/session_mode), so create_all and
    # the chain converge on the same final shape (see test_schema_drift).
    existing = set(sa.inspect(bind).get_table_names(schema="web"))
    if "conversations" not in existing:
        op.create_table(
            "conversations",
            sa.Column("conversation_id", sa.String, primary_key=True),
            sa.Column("title", sa.String, nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            schema="web",
        )
    if "conversation_messages" not in existing:
        op.create_table(
            "conversation_messages",
            sa.Column("message_id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "conversation_id",
                sa.String,
                sa.ForeignKey("web.conversations.conversation_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("ai_sdk_message_id", sa.String, nullable=True),
            sa.Column("seq", sa.Integer, nullable=False),
            sa.Column("role", sa.String, nullable=False),
            sa.Column("parts", sa.JSON, nullable=False),
            sa.Column(
                "status",
                sa.String,
                nullable=False,
                server_default=sa.text("'complete'"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "status IN ('streaming', 'complete', 'error')",
                name="ck_conversation_messages_status",
            ),
            schema="web",
        )
        op.create_index(
            "ix_conv_messages_conv_seq",
            "conversation_messages",
            ["conversation_id", "seq"],
            schema="web",
        )
        op.create_index(
            "uq_conv_messages_ai_sdk_id",
            "conversation_messages",
            ["conversation_id", "ai_sdk_message_id"],
            unique=True,
            schema="web",
            postgresql_where=sa.text("ai_sdk_message_id IS NOT NULL"),
        )

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
