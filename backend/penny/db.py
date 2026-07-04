"""Lazy DB singleton.

The agent-facing tools and the bootstrap step share one ``DB`` instance per
process. URL comes from ``$DATABASE_URL`` (defaults to a local SQLite file
at ``./penny.db`` for dev).
"""

from __future__ import annotations

import os

from .adapters.db.facade import DB

_DEFAULT_URL = "sqlite:///./penny.db"

_db: DB | None = None
_readonly_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        url = os.environ.get("DATABASE_URL", "").strip() or _DEFAULT_URL
        _db = DB(url, enforce_sqlite_fks=url.startswith("sqlite"))
    return _db


def get_readonly_db() -> DB:
    """DB handle for the agent's free-form ``run_sql`` — a read-only role in prod.

    Bound to ``PENNY_AGENT_READONLY_DATABASE_URL`` (a Postgres role granted only
    ``SELECT``) so a prompt-injected ``DELETE``/``UPDATE`` is rejected by the
    database itself, not merely by convention. RLS still applies because the tool
    runs under ``session_for(ctx)``. In dev mode (SQLite has no roles) it falls
    back to the primary DB; in clerk mode an unset URL is a hard misconfiguration
    (fail closed) so prod never runs free-form SQL on a read-write connection.
    """
    global _readonly_db
    if _readonly_db is None:
        url = os.environ.get("PENNY_AGENT_READONLY_DATABASE_URL", "").strip()
        if not url:
            from penny.auth.settings import load_auth_settings

            if load_auth_settings().mode == "clerk":
                raise RuntimeError(
                    "PENNY_AGENT_READONLY_DATABASE_URL is required in clerk mode"
                )
            return get_db()  # dev/SQLite fallback
        # On Postgres the read-only role has EXECUTE on set_config revoked (F02/
        # F05), so pin the tenant GUCs through the set-once penny_set_tenant
        # wrapper rather than a direct set_config the untrusted SQL could re-issue.
        is_sqlite = url.startswith("sqlite")
        _readonly_db = DB(
            url,
            enforce_sqlite_fks=is_sqlite,
            use_tenant_guc_wrapper=not is_sqlite,
        )
    return _readonly_db
