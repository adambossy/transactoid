"""Postgres row-level-security policy DDL for the finance schema.

Single source of the ``tenant_isolation`` policy shape, executed by migration
015 on prod/test Postgres and by the ``pg_db`` test fixture against throwaway
schemas. SQLite has no RLS — there, app-level filtering
(``facade.visible_filter``) is the only tenant layer.

Policy semantics (both USING and WITH CHECK, so reads AND writes are fenced):

- owner/visibility tables: row belongs to the session's household AND is
  either owned by the session's user or shared. In a joint session
  ``app.current_user`` is the nil-UUID sentinel, which matches no real owner
  (rows can't be nil-owned — see migration 014's CHECK), so only shared rows
  pass.
- household-only tables (incl. plaid_items, whose privacy lives per-account):
  row belongs to the session's household.

``FORCE`` applies the policy to the table owner too — the app role that
created the tables gets no bypass. Identity tables (households/users) carry
no policy: resolving a principal happens before a tenant context exists.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Tables carrying household_id / owner_user_id / visibility (mirrors
# migrations 011/012/014).
OWNER_VIS_TABLES = [
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
# Tables scoped by household only. categories joins via migration 016, which
# adds its household_id column and policy together.
HOUSEHOLD_ONLY_TABLES = ["plaid_items", "tags", "transaction_category_events"]

_OWNER_VIS_PREDICATE = """
    household_id = current_setting('app.current_household', true)::uuid
    AND (owner_user_id = current_setting('app.current_user', true)::uuid
         OR visibility = 'shared')
"""
_HOUSEHOLD_PREDICATE = """
    household_id = current_setting('app.current_household', true)::uuid
"""


def household_policy_ddl(table: str, *, owner_vis: bool) -> list[str]:
    """The DDL statements enabling the tenant_isolation policy on ``table``."""
    predicate = _OWNER_VIS_PREDICATE if owner_vis else _HOUSEHOLD_PREDICATE
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({predicate}) WITH CHECK ({predicate})",
    ]


def enable_rls(conn: Connection) -> None:
    """Enable RLS + create tenant_isolation policies on every tenant table."""
    for table in OWNER_VIS_TABLES:
        for ddl in household_policy_ddl(table, owner_vis=True):
            conn.execute(text(ddl))
    for table in HOUSEHOLD_ONLY_TABLES:
        for ddl in household_policy_ddl(table, owner_vis=False):
            conn.execute(text(ddl))


def disable_rls(conn: Connection) -> None:
    """Drop the tenant_isolation policies and disable RLS (idempotent)."""
    for table in OWNER_VIS_TABLES + HOUSEHOLD_ONLY_TABLES:
        conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
