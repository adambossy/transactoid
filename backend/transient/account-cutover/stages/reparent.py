"""Stage 4 — apply the mapping, denormalize onto children, assert 0 unassigned.

Runs entirely inside one transaction (committed on a real run, rolled back on
``--dry-run`` after reporting per-table row counts). The design is *copy from
the anchor*:

1. Upsert ``plaid_accounts`` from the mapping (the per-account owner/household/
   visibility anchor).
2. Set ``amazon_login_profiles`` from the mapping's amazon section.
3. Copy the tenant columns *down* the FK graph with ``UPDATE ... FROM`` — each
   child copies from its parent (``SCOPED_TABLES`` is ordered so every parent is
   assigned before its children): plaid_transactions/plaid_items/email_receipts/
   account_sign_conventions from plaid_accounts; derived_transactions from its
   plaid_transaction; transaction_items/tags/pending_receipt_matches from their
   derived_transaction; amazon_orders/items from their profile/order.
4. Assign the household-only tables (``tags``, ``transaction_category_events``)
   to the single household.
5. Encrypt any plaintext ``plaid_items.access_token`` (idempotent; 017 also does
   this during finalize, but the plan pins it here).

``categories`` and ``web.conversations`` are deliberately NOT touched: their
tenant columns are added by the CONTRACT half (016/019), so they don't exist
yet — finalize handles them.

**Post-condition:** after the copies, every existing tenant column on every
scoped table must be non-NULL. If any remain NULL the transaction is rolled back
and the stage aborts loudly — nothing slips before the NOT-NULL/RLS contract.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import sqlalchemy as sa
import yaml

from common import (
    SCOPED_TABLES,
    CutoverState,
    ScopedTable,
    echo,
    existing_tenant_columns,
    make_engine,
    require,
    resolve_db_url,
    table_exists,
)

STAGE = "reparent"


def _uuid_stmt(sql: str, *names: str) -> sa.TextClause:
    return sa.text(sql).bindparams(*(sa.bindparam(n, type_=sa.Uuid()) for n in names))


def _u(value: str) -> uuid.UUID:
    """Coerce a mapping/state id string to a UUID (the typed Uuid binds need
    UUID objects; the mapping stores them as strings)."""
    return uuid.UUID(str(value))


def run(*, db_url: str | None, mapping_file: str, state_file: str, dry_run: bool) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    mapping = yaml.safe_load(Path(mapping_file).read_text()) or {}
    require(mapping.get("accounts"), f"{mapping_file} has no accounts — run assign-accounts first")
    household_id = mapping.get("household_id") or state.get("household_id")
    require(bool(household_id), "no household_id in mapping or state — run bootstrap")

    engine = make_engine(url)
    counts: dict[str, int] = {}
    conn = engine.connect()
    trans = conn.begin()
    try:
        _upsert_accounts(conn, mapping, household_id, counts)
        _validate_single_owner_per_item(conn)
        _set_amazon_profiles(conn, mapping, household_id, counts)

        for st in SCOPED_TABLES:
            if st.name in ("plaid_accounts", "amazon_login_profiles"):
                continue  # anchors, handled above
            if not table_exists(conn, st.name):
                continue
            if st.copy_from is None:
                # Household-only table (tags, transaction_category_events).
                counts[st.name] = _assign_household(conn, st.name, household_id)
            else:
                counts[st.name] = _copy_from_parent(conn, st)

        enc = _encrypt_tokens(conn)

        unassigned = _post_condition(conn)

        echo("Row counts touched:")
        for name in sorted(counts):
            echo(f"  {name}: {counts[name]}")
        echo(f"  plaid_items.access_token encrypted: {enc}")

        if unassigned:
            echo("UNASSIGNED tenant columns remain:")
            for tbl_col, n in unassigned.items():
                echo(f"  {tbl_col}: {n} NULL")
            if dry_run:
                echo("[dry-run] post-condition would FAIL (see above). Rolling back.")
                trans.rollback()
                return
            trans.rollback()
            require(False, "post-condition failed: NULL tenant columns remain after reparent")

        if dry_run:
            echo("[dry-run] post-condition OK (zero unassigned). Rolling back — no writes.")
            trans.rollback()
            return

        trans.commit()
        state.mark_done(STAGE)
        echo("Reparent committed. Post-condition holds: zero unassigned tenant columns.")
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Anchors                                                                      #
# --------------------------------------------------------------------------- #


def _upsert_accounts(conn: sa.Connection, mapping: dict, household_id: str, counts: dict[str, int]) -> None:
    """Insert or update one plaid_accounts row per mapping account (the anchor)."""
    n = 0
    for a in mapping["accounts"]:
        params = {
            "a": a["account_id"],
            "i": a["item_id"],
            "u": _u(a["owner_user_id"]),
            "h": _u(household_id),
            "v": a["visibility"],
        }
        updated = conn.execute(
            _uuid_stmt(
                "UPDATE plaid_accounts SET item_id=:i, owner_user_id=:u, household_id=:h, "
                "visibility=:v WHERE account_id=:a",
                "u",
                "h",
            ),
            params,
        ).rowcount
        if not updated:
            conn.execute(
                _uuid_stmt(
                    "INSERT INTO plaid_accounts (account_id, item_id, owner_user_id, household_id, "
                    "visibility) VALUES (:a, :i, :u, :h, :v)",
                    "u",
                    "h",
                ),
                params,
            )
        n += 1
    counts["plaid_accounts"] = n


def _validate_single_owner_per_item(conn: sa.Connection) -> None:
    """plaid_items copies its owner from its accounts, so an item whose accounts
    map to two different owners is ambiguous — abort rather than pick one."""
    bad = conn.execute(
        sa.text(
            "SELECT item_id FROM plaid_accounts GROUP BY item_id "
            "HAVING COUNT(DISTINCT owner_user_id) > 1"
        )
    ).all()
    require(not bad, f"items with multiple owners across their accounts: {[b[0] for b in bad]}")


def _set_amazon_profiles(conn: sa.Connection, mapping: dict, household_id: str, counts: dict[str, int]) -> None:
    profiles = mapping.get("amazon_profiles") or []
    if not profiles or not table_exists(conn, "amazon_login_profiles"):
        return
    n = 0
    for p in profiles:
        n += conn.execute(
            _uuid_stmt(
                "UPDATE amazon_login_profiles SET household_id=:h, owner_user_id=:u, visibility=:v "
                "WHERE profile_id=:p",
                "h",
                "u",
            ),
            {"h": _u(household_id), "u": _u(p["owner_user_id"]), "v": p["visibility"], "p": p["profile_id"]},
        ).rowcount
    counts["amazon_login_profiles"] = n


# --------------------------------------------------------------------------- #
# Copy-down + household assignment                                             #
# --------------------------------------------------------------------------- #


def _copy_from_parent(conn: sa.Connection, st: ScopedTable) -> int:
    """``UPDATE child SET <tenant cols> = src.<cols> FROM parent AS src WHERE <join>``."""
    parent, predicate = st.copy_from  # type: ignore[misc]
    set_clause = ", ".join(f"{c}=src.{c}" for c in st.columns)
    sql = f"UPDATE {st.name} SET {set_clause} FROM {parent} AS src WHERE {predicate}"  # noqa: S608
    return conn.execute(sa.text(sql)).rowcount


def _assign_household(conn: sa.Connection, table: str, household_id: str) -> int:
    return conn.execute(
        _uuid_stmt(f"UPDATE {table} SET household_id=:h", "h"),  # noqa: S608
        {"h": _u(household_id)},
    ).rowcount


def _encrypt_tokens(conn: sa.Connection) -> int:
    """Encrypt plaintext plaid_items.access_token at rest (idempotent)."""
    if not table_exists(conn, "plaid_items"):
        return 0
    from penny.security.token_cipher import encrypt_token, is_encrypted

    rows = conn.execute(sa.text("SELECT item_id, access_token FROM plaid_items")).all()
    plaintext = [(i, t) for i, t in rows if t and not is_encrypted(t)]
    if plaintext and not os.environ.get("PENNY_PLAID_TOKEN_KEY", "").strip():
        echo("  note: plaintext tokens present but PENNY_PLAID_TOKEN_KEY unset — "
             "leaving for migration 017 (finalize), which fails loudly without the key.")
        return 0
    for item_id, token in plaintext:
        conn.execute(
            sa.text("UPDATE plaid_items SET access_token=:t WHERE item_id=:i"),
            {"t": encrypt_token(token), "i": item_id},
        )
    return len(plaintext)


# --------------------------------------------------------------------------- #
# Post-condition                                                               #
# --------------------------------------------------------------------------- #


def _post_condition(conn: sa.Connection) -> dict[str, int]:
    """Every existing tenant column on every scoped table must be non-NULL.

    Introspects which columns exist (categories/workspace/web.conversations are
    absent pre-finalize and skipped), so the assertion is honest about the live
    schema. Returns {``table.column``: null_count} for any offenders (empty ==
    pass)."""
    offenders: dict[str, int] = {}
    for st in SCOPED_TABLES:
        if not table_exists(conn, st.name):
            continue
        present = existing_tenant_columns(conn, st.name)
        for col in st.columns:
            if col not in present:
                continue
            n = conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {st.name} WHERE {col} IS NULL")  # noqa: S608
            ).scalar_one()
            if n:
                offenders[f"{st.name}.{col}"] = n
    return offenders
