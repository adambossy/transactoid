"""Enable RLS tenant_isolation policies (Postgres only)

Revision ID: 015_enable_rls_policies
Revises: 014_tenant_columns_not_null_and_fks
Create Date: 2026-07-03

Creates the ``tenant_isolation`` policy (USING **and** WITH CHECK, so a tenant
can neither read nor write another household's rows) on every tenant table
that exists at this point in the chain. The policy *shape* is shared with the
``pg_db`` test fixture via ``penny.adapters.db.rls.household_policy_ddl``; the
table lists are snapshotted here so later tables (categories, migration 016)
don't retroactively change this revision. SQLite skips this entirely: no RLS
there, app-level filtering is the tenant layer.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_enable_rls_policies"
down_revision: str | Sequence[str] | None = "014_tenant_columns_not_null_and_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_VIS = [
    "plaid_accounts",
    "plaid_transactions",
    "derived_transactions",
    "transaction_items",
    "transaction_tags",
    "email_receipts",
    "pending_receipt_matches",
    "account_sign_conventions",
    "amazon_login_profiles",
    "amazon_orders",
    "amazon_items",
]
HOUSEHOLD_ONLY = ["plaid_items", "tags", "transaction_category_events"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from penny.adapters.db.rls import household_policy_ddl

    for table in OWNER_VIS:
        for ddl in household_policy_ddl(table, owner_vis=True):
            op.execute(ddl)
    for table in HOUSEHOLD_ONLY:
        for ddl in household_policy_ddl(table, owner_vis=False):
            op.execute(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in OWNER_VIS + HOUSEHOLD_ONLY:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
