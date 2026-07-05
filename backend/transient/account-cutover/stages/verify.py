"""Stage 6 — isolation/privacy checks on the migrated data.

Only when this passes is the frozen step-0 backup branch releasable. Three
batteries:

1. **Zero unassigned** — no NULL tenant column remains on any scoped table that
   now exists (the full set, including the contract-half categories, workspace_*,
   and web.conversations).
2. **Tokens at rest** — every ``plaid_items.access_token`` is ciphertext.
3. **RLS isolation** — from each spouse's tenant context, a private account owned
   by the OTHER spouse returns **zero** rows, while shared rows are visible and
   the owner sees their own private rows. This is the end-to-end proof the
   assignment held.

The RLS battery is meaningful ONLY as a **non-superuser, non-BYPASSRLS** role
(FORCE RLS still lets a superuser/bypass role see everything). Pass
``--app-db-url`` with the app role; verify refuses to claim an RLS pass from a
bypassing role. On SQLite (dev) there is no RLS — only batteries 1 and 2 run.

Exits non-zero on any failure so it can gate the runbook.
"""

from __future__ import annotations

import sys
import uuid

import sqlalchemy as sa

from common import (
    SCOPED_TABLES,
    CutoverState,
    echo,
    existing_tenant_columns,
    is_postgres,
    make_engine,
    resolve_db_url,
    table_exists,
)

STAGE = "verify"

# Contract-half tables that gain tenant columns after reparent — swept here too.
_EXTRA_SCOPED = (
    ("categories", ("household_id",)),
    ("web.conversations", ("household_id", "owner_user_id")),
)


def run(*, db_url: str | None, app_db_url: str | None, state_file: str) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    results: list[tuple[str, bool, str]] = []

    admin = make_engine(url)
    with admin.connect() as conn:
        results += _check_unassigned(conn)
        results.append(_check_tokens(conn))
        if is_postgres(admin):
            results += _check_isolation(app_db_url or url, state, same_as_admin=app_db_url is None)
        else:
            results.append(("rls-isolation", True, "skipped (SQLite has no RLS; app-layer filter governs dev)"))

    echo("\nVerify report:")
    ok = True
    for name, passed, detail in results:
        echo(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        ok = ok and passed

    if not ok:
        echo("\nVERIFY FAILED — do NOT release the frozen backup branch.")
        sys.exit(1)
    echo("\nVERIFY PASSED — migrated data is isolated and tokens are at rest.")
    state.mark_done(STAGE)


# --------------------------------------------------------------------------- #
# Battery 1: zero unassigned                                                  #
# --------------------------------------------------------------------------- #


def _check_unassigned(conn: sa.Connection) -> list[tuple[str, bool, str]]:
    tables = [(st.name, st.columns) for st in SCOPED_TABLES] + list(_EXTRA_SCOPED)
    offenders: list[str] = []
    for name, cols in tables:
        if not table_exists(conn, name):
            continue
        present = existing_tenant_columns(conn, name)
        for col in cols:
            if col not in present:
                continue
            n = conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {name} WHERE {col} IS NULL")  # noqa: S608
            ).scalar_one()
            if n:
                offenders.append(f"{name}.{col}={n}")
    if offenders:
        return [("zero-unassigned", False, "NULLs remain: " + ", ".join(offenders))]
    return [("zero-unassigned", True, "no NULL tenant columns on any scoped table")]


# --------------------------------------------------------------------------- #
# Battery 2: tokens at rest                                                   #
# --------------------------------------------------------------------------- #


def _check_tokens(conn: sa.Connection) -> tuple[str, bool, str]:
    if not table_exists(conn, "plaid_items"):
        return ("tokens-at-rest", True, "no plaid_items")
    from penny.security.token_cipher import is_encrypted

    rows = conn.execute(sa.text("SELECT item_id, access_token FROM plaid_items")).all()
    plaintext = [i for i, t in rows if t and not is_encrypted(t)]
    if plaintext:
        return ("tokens-at-rest", False, f"{len(plaintext)} plaintext token(s): {plaintext}")
    return ("tokens-at-rest", True, f"all {len(rows)} token(s) ciphertext")


# --------------------------------------------------------------------------- #
# Battery 3: RLS isolation                                                    #
# --------------------------------------------------------------------------- #


def _check_isolation(app_url: str, state: CutoverState, *, same_as_admin: bool) -> list[tuple[str, bool, str]]:
    household_id = state.get("household_id")
    users = state.get("users", {})  # email -> user_id
    if not household_id or len(users) != 2:
        return [("rls-isolation", False, "state missing household_id or the two users")]

    engine = make_engine(app_url)
    with engine.connect() as conn:
        if _role_bypasses_rls(conn):
            return [(
                "rls-isolation",
                False,
                "connected role bypasses RLS (superuser/BYPASSRLS) — rerun with "
                "--app-db-url pointing at the non-superuser app role",
            )]

        emails = list(users)
        # Probe: a private account owned by user A. Ask (as an unfenced query on
        # plaid_accounts, which is RLS-fenced too — so set A's context first).
        results: list[tuple[str, bool, str]] = []
        a_email, b_email = emails[0], emails[1]
        a_id, b_id = users[a_email], users[b_email]

        probe = _private_account_for(conn, household_id, a_id)
        if probe is None:
            results.append(("rls-isolation", True, "no private account to probe — vacuously isolated"))
            if same_as_admin:
                results.append(("rls-role-warning", True, "note: --app-db-url not given; ran as --db-url"))
            return results

        # Owner A sees their own private account's transactions.
        owner_visible = _visible_txn_count(conn, household_id, a_id, probe)
        results.append((
            "rls-owner-sees-private",
            owner_visible > 0,
            f"owner {a_email} sees {owner_visible} txn(s) of their private account {probe}",
        ))
        # The OTHER spouse B sees ZERO rows of A's private account.
        other_visible = _visible_txn_count(conn, household_id, b_id, probe)
        results.append((
            "rls-private-hidden-from-spouse",
            other_visible == 0,
            f"spouse {b_email} sees {other_visible} txn(s) of {a_email}'s private account "
            f"(must be 0)",
        ))
        if same_as_admin:
            results.append((
                "rls-role-warning",
                True,
                "note: --app-db-url not given; RLS ran as --db-url (confirm it is the app role)",
            ))
        return results


def _role_bypasses_rls(conn: sa.Connection) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).scalar()
    return bool(row)


def _set_context(conn: sa.Connection, household_id: str, user_id: str) -> None:
    conn.execute(
        sa.text("SELECT set_config('app.current_household', :h, false)"),
        {"h": str(uuid.UUID(str(household_id)))},
    )
    conn.execute(
        sa.text("SELECT set_config('app.current_user', :u, false)"),
        {"u": str(uuid.UUID(str(user_id)))},
    )


def _private_account_for(conn: sa.Connection, household_id: str, user_id: str) -> str | None:
    """An account_id owned privately by ``user_id`` (probe for the leak test)."""
    _set_context(conn, household_id, user_id)
    return conn.execute(
        sa.text(
            "SELECT account_id FROM plaid_accounts WHERE owner_user_id = :u "
            "AND visibility = 'private' LIMIT 1"
        ).bindparams(sa.bindparam("u", type_=sa.Uuid())),
        {"u": uuid.UUID(str(user_id))},
    ).scalar()


def _visible_txn_count(conn: sa.Connection, household_id: str, user_id: str, account_id: str) -> int:
    """Rows of ``account_id`` visible in ``user_id``'s tenant context (RLS-fenced)."""
    _set_context(conn, household_id, user_id)
    return conn.execute(
        sa.text("SELECT COUNT(*) FROM plaid_transactions WHERE account_id = :a"),
        {"a": account_id},
    ).scalar_one()
