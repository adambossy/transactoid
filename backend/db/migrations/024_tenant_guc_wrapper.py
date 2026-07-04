"""Install the set-once penny_set_tenant GUC wrapper (Postgres only)

Revision ID: 024_tenant_guc_wrapper
Revises: 023_add_queued_reminders
Create Date: 2026-07-04

Security fix F02/F05: the read-only ``run_sql`` connection pins its
transaction-local tenant binding through the ``penny_set_tenant`` SECURITY
DEFINER wrapper instead of a direct ``set_config``. The wrapper is *set-once*, so
untrusted agent SQL cannot flip ``app.current_household`` mid-transaction (e.g.
via a ``WITH c AS (SELECT set_config(...)) …`` CTE) to read another household's
rows. The companion role hardening — ``REVOKE EXECUTE ON set_config … FROM
PUBLIC`` plus the grants — is deployment-specific (it names the agent + owner
roles) and lives with the rest of the read-only role DDL in ``.env.example``.

The wrapper DDL is shared with the ``pg_db`` test fixture via
``penny.adapters.db.rls.install_tenant_guc_wrapper`` (CREATE OR REPLACE, so this
is idempotent on the create_all-managed prod schema). SQLite has no RLS and skips
this entirely.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "024_tenant_guc_wrapper"
down_revision: str | Sequence[str] | None = "023_add_queued_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from penny.adapters.db.rls import install_tenant_guc_wrapper

    install_tenant_guc_wrapper(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP FUNCTION IF EXISTS penny_set_tenant(text, text)")
