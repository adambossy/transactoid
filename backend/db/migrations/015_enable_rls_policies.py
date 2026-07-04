"""Enable RLS tenant_isolation policies (Postgres only)

Revision ID: 015_enable_rls_policies
Revises: 014_tenant_columns_not_null_and_fks
Create Date: 2026-07-03

Creates the ``tenant_isolation`` policy (USING **and** WITH CHECK, so a tenant
can neither read nor write another household's rows) on every tenant table.
The policy DDL lives in ``penny.adapters.db.rls`` — shared with the ``pg_db``
test fixture. SQLite skips this entirely: no RLS there, app-level filtering
is the tenant layer.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_enable_rls_policies"
down_revision: str | Sequence[str] | None = "014_tenant_columns_not_null_and_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from penny.adapters.db.rls import enable_rls

    enable_rls(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from penny.adapters.db.rls import disable_rls

    disable_rls(bind)
