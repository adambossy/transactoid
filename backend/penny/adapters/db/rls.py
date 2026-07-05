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
    # Phase 1b workspace store — same household/owner/visibility triple, same
    # policy. Migration 018 enables these on prod; this list backs the pg_db
    # test fixture (migration 015 snapshots its own frozen list, so appending
    # here does not retroactively change 015).
    "workspace_prefixes",
    "workspace_manifests",
    "workspace_heads",
]
# Tables scoped by household only. In the migration chain, categories'
# policy lands in 016 (with its household_id column), after 015 creates the
# rest — 015 snapshots its own table lists for that reason.
HOUSEHOLD_ONLY_TABLES = [
    "plaid_items",
    "tags",
    "transaction_category_events",
    "categories",
]

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


# The read-only agent connection pins its transaction-local tenant binding
# through this SECURITY DEFINER wrapper — never via a direct ``set_config`` that
# the agent's own (untrusted) run_sql SQL could also issue. The wrapper is
# *set-once*: ``_apply_rls_settings`` pins the household at session open, and any
# later call in the same transaction is rejected. So an injected single-statement
# override such as
#     WITH c AS (SELECT penny_set_tenant('<victim>', '<victim>')) SELECT * FROM …
# raises instead of flipping the household before RLS evaluates the scan. Paired
# with revoking EXECUTE on ``set_config`` from the agent role (see
# ``revoke_guc_override``), this closes the GUC-override RLS bypass (findings
# F02/F05). Owned by the privileged role that runs it (the app/migration owner),
# so the definer retains EXECUTE on ``set_config`` after the PUBLIC revoke.
_TENANT_GUC_WRAPPER_FN = """
CREATE OR REPLACE FUNCTION penny_set_tenant(p_household text, p_user text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF coalesce(current_setting('app.current_household', true), '') <> '' THEN
        RAISE EXCEPTION 'tenant context is already set for this transaction';
    END IF;
    PERFORM set_config('app.current_household', p_household, true);
    PERFORM set_config('app.current_user', p_user, true);
END;
$$
"""


def install_tenant_guc_wrapper(conn: Connection) -> None:
    """Create the set-once ``penny_set_tenant`` wrapper (idempotent).

    Installed alongside RLS so every Postgres deployment the app talks to — prod
    (migration) and the ``pg_db`` test fixture — carries it; the read-only
    ``run_sql`` connection calls it in place of ``set_config``.
    """
    conn.execute(text(_TENANT_GUC_WRAPPER_FN))
    conn.execute(
        text("REVOKE ALL ON FUNCTION penny_set_tenant(text, text) FROM PUBLIC")
    )


def revoke_guc_override(conn: Connection, *, agent_role: str, owner_role: str) -> None:
    """Deny the agent role the ability to flip the tenant GUC mid-transaction.

    ``set_config`` EXECUTE is granted to PUBLIC by default, so a per-role REVOKE
    is a no-op; the grant must be revoked from PUBLIC and re-granted to the
    privileged ``owner_role`` (which runs curated code and owns/defines the
    wrapper). The agent role instead gets EXECUTE on the set-once
    ``penny_set_tenant`` wrapper — its only legitimate way to pin a context.
    Closes findings F02/F05.
    """
    conn.execute(
        text(
            "REVOKE EXECUTE ON FUNCTION "
            "pg_catalog.set_config(text, text, boolean) FROM PUBLIC"
        )
    )
    conn.execute(
        text(
            "GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) "
            f'TO "{owner_role}"'
        )
    )
    conn.execute(
        text(
            f'GRANT EXECUTE ON FUNCTION penny_set_tenant(text, text) TO "{agent_role}"'
        )
    )


# Identity tables carry no RLS policy (a principal is resolved before any tenant
# context exists), so a blanket ``GRANT SELECT ON ALL TABLES`` to the agent role
# would let run_sql read every row of them regardless of household.
_IDENTITY_TABLES = ("users", "households")


def revoke_identity_table_reads(conn: Connection, *, agent_role: str) -> None:
    """Keep the RLS-exempt identity tables out of the agent role's reach (F04).

    Without this, run_sql on the read-only role can ``SELECT email,
    external_auth_id FROM users`` / ``SELECT household_id FROM households`` and
    enumerate every user's email + Clerk id and every household UUID across all
    tenants — the latter also being the pre-condition for the F02 override.
    The app's own (privileged) access to these tables is unaffected.
    """
    tables = ", ".join(_IDENTITY_TABLES)  # fixed identifiers, not user input
    conn.execute(text(f'REVOKE SELECT ON {tables} FROM "{agent_role}"'))  # noqa: S608


def enable_rls(conn: Connection) -> None:
    """Enable RLS + create tenant_isolation policies on every tenant table."""
    install_tenant_guc_wrapper(conn)
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
