"""Shared plumbing for the phase-3 cutover stages.

TRANSIENT / NON-CANONICAL (see AGENTS.md): this whole tree is a one-off tool,
exempt from the lint/test gate and deletable once the cutover completes. It may
import the canonical phase-1a models/facade, the token cipher, and the tenancy
constants **read-only** (it never writes app code and no app code imports it).

This module owns the pieces every stage needs:

- ``CutoverState`` — the resumable, idempotent ``.cutover-state.json`` record.
- DB-URL resolution + a plain SQLAlchemy engine (writes go through parameterized
  SQL, not the ORM: the schema morphs mid-run as the two migration halves land,
  so the ORM models would not match the live table shape at every stage).
- ``run_alembic`` — a thin subprocess wrapper around the canonical alembic
  config, used by ``reconcile-expand`` (expand half) and ``finalize-schema``
  (contract half). The chain is applied in two ``upgrade`` calls around the
  interactive assignment.
- ``SCOPED_TABLES`` — the single source of truth for which finance tables carry
  which tenant columns and how each reaches its owning account. reparent uses it
  to denormalize and to assert the zero-unassigned post-condition; verify uses
  it to sweep for leftover NULLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

# ``backend/`` — two levels up from ``backend/transient/account-cutover``. The
# canonical alembic config lives at ``backend/alembic.ini``.
BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# The pre-tenancy head: prod's ``create_all`` schema matches the models at this
# revision, so reconcile stamps it as the applied baseline before upgrading.
BASELINE_REVISION = "009_add_plaid_raw_name_and_enrichment"
# Expand half: identity tables, plaid_accounts, nullable tenant columns, and the
# dev-only (prod no-op) backfill. Stops here so the interactive assignment can
# run before any NOT-NULL/RLS contract lands.
EXPAND_HEAD = "013_backfill_tenant_columns"
# Contract half is ``alembic upgrade head`` (currently 021) — NOT NULL + FKs +
# CHECKs + RLS (014/015), per-household categories (016), token encryption
# (017), workspace store (018), conversation tenancy + web RLS (019), and the
# phase-2b billing tables (020/021). It can only land after every legacy row is
# assigned, which is why it is a *separate* upgrade after reparent.
CONTRACT_HEAD = "head"


# --------------------------------------------------------------------------- #
# Scoped-table metadata (single source for reparent + verify)                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScopedTable:
    """A finance table that carries denormalized tenant columns.

    ``columns`` is the subset of (household_id, owner_user_id, visibility) the
    table actually has. ``copy_from`` names the parent table + join predicate
    the tenant columns are *copied down* from during reparent (``None`` for the
    account/profile anchors, which are set directly from the mapping). Tables
    whose columns only appear in the contract half (categories, workspace_*,
    web.conversations) are intentionally absent — see reparent/finalize.
    """

    name: str
    columns: tuple[str, ...]
    copy_from: tuple[str, str] | None = None  # (parent_table, join_predicate)


# household_id / owner_user_id / visibility unless noted. The account anchor is
# ``plaid_accounts`` (upserted from the mapping); everything else copies down.
_OWNER_VIS = ("household_id", "owner_user_id", "visibility")
_HOUSEHOLD = ("household_id",)

SCOPED_TABLES: tuple[ScopedTable, ...] = (
    # Anchors set directly from the mapping (copy_from=None).
    ScopedTable("plaid_accounts", _OWNER_VIS),
    # plaid_items carries no visibility (an item's privacy is per-account); its
    # owner is copied from its accounts (validated single-owner-per-item first).
    ScopedTable(
        "plaid_items",
        ("household_id", "owner_user_id"),
        ("plaid_accounts", "plaid_items.item_id = src.item_id"),
    ),
    # Account-anchored: copy straight from plaid_accounts by account_id.
    ScopedTable(
        "plaid_transactions",
        _OWNER_VIS,
        ("plaid_accounts", "plaid_transactions.account_id = src.account_id"),
    ),
    ScopedTable(
        "account_sign_conventions",
        _OWNER_VIS,
        ("plaid_accounts", "account_sign_conventions.account_id = src.account_id"),
    ),
    # Transaction chain: derived copies from its plaid_transaction; the rest copy
    # from derived_transactions.
    ScopedTable(
        "derived_transactions",
        _OWNER_VIS,
        (
            "plaid_transactions",
            "derived_transactions.plaid_transaction_id = src.plaid_transaction_id",
        ),
    ),
    ScopedTable(
        "transaction_items",
        _OWNER_VIS,
        ("derived_transactions", "transaction_items.transaction_id = src.transaction_id"),
    ),
    # email_receipts has NO account_id column. A receipt reaches its owning
    # account only through the itemization it produced: transaction_items with
    # itemization_source='email_receipt' carry source_ref=message_id (see the
    # EmailReceipt/TransactionItem models). So it copies tenant columns down from
    # transaction_items on message_id = source_ref — which is why it is ordered
    # AFTER transaction_items (its parent must be assigned first). message_id is
    # unique per receipt and every matching item shares one transaction/account,
    # so the owner is unambiguous.
    ScopedTable(
        "email_receipts",
        _OWNER_VIS,
        (
            "transaction_items",
            "email_receipts.message_id = src.source_ref "
            "AND src.itemization_source = 'email_receipt'",
        ),
    ),
    ScopedTable(
        "transaction_tags",
        _OWNER_VIS,
        ("derived_transactions", "transaction_tags.transaction_id = src.transaction_id"),
    ),
    ScopedTable(
        "pending_receipt_matches",
        _OWNER_VIS,
        ("derived_transactions", "pending_receipt_matches.candidate_txn_id = src.transaction_id"),
    ),
    # Amazon: profiles are anchors (set from the mapping's amazon section);
    # orders copy from their profile, items from their order.
    ScopedTable("amazon_login_profiles", _OWNER_VIS),
    ScopedTable(
        "amazon_orders",
        _OWNER_VIS,
        ("amazon_login_profiles", "amazon_orders.profile_id = src.profile_id"),
    ),
    ScopedTable(
        "amazon_items",
        _OWNER_VIS,
        ("amazon_orders", "amazon_items.order_id = src.order_id"),
    ),
    # Household-only (no owner/visibility): assigned to the single cutover
    # household directly.
    ScopedTable("tags", _HOUSEHOLD),
    ScopedTable("transaction_category_events", _HOUSEHOLD),
)


# --------------------------------------------------------------------------- #
# State file                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class CutoverState:
    """The resumable run record persisted to ``.cutover-state.json``.

    ``completed`` gates idempotency (a re-run skips finished stages unless
    ``--force``); ``artifacts`` carries values later stages need (the frozen
    branch name, the household + user ids bootstrap created).
    """

    path: Path
    completed: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> CutoverState:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            return cls(
                path=p,
                completed=list(data.get("completed", [])),
                artifacts=dict(data.get("artifacts", {})),
            )
        return cls(path=p)

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {"completed": self.completed, "artifacts": self.artifacts},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def is_done(self, stage: str) -> bool:
        return stage in self.completed

    def mark_done(self, stage: str) -> None:
        if stage not in self.completed:
            self.completed.append(stage)
        self.save()

    def set(self, key: str, value: Any) -> None:
        self.artifacts[key] = value
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)


# --------------------------------------------------------------------------- #
# DB + alembic                                                                #
# --------------------------------------------------------------------------- #


def resolve_db_url(db_url: str | None) -> str:
    """The explicit ``--db-url`` or ``$DATABASE_URL``; fail loudly if neither."""
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "No database URL: pass --db-url or set DATABASE_URL "
            "(point it at the REHEARSAL branch, never prod, until verify passes)."
        )
    return url


def make_engine(db_url: str) -> Engine:
    """A plain engine for parameterized cutover SQL (future-style, no pooling
    surprises). The ORM is deliberately not used — the live schema changes shape
    between the expand and contract halves."""
    return sa.create_engine(db_url, future=True)


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def table_exists(conn: sa.Connection, table: str) -> bool:
    """True if ``table`` (optionally ``schema.table``) exists in the live DB."""
    schema, _, name = table.partition(".") if "." in table else ("", "", table)
    insp = sa.inspect(conn)
    return insp.has_table(name, schema=schema or None)


def existing_tenant_columns(conn: sa.Connection, table: str) -> set[str]:
    """Which of the tenant columns physically exist on ``table`` right now.

    reparent/verify introspect rather than assume: categories, workspace_*, and
    web.conversations only gain their columns in the contract half, so before
    finalize they must be skipped, not errored on.
    """
    schema, _, name = table.partition(".") if "." in table else ("", "", table)
    insp = sa.inspect(conn)
    if not insp.has_table(name, schema=schema or None):
        return set()
    cols = {c["name"] for c in insp.get_columns(name, schema=schema or None)}
    return cols & {"household_id", "owner_user_id", "visibility"}


def run_alembic(db_url: str, target: str, *, dry_run: bool, extra_env: dict[str, str] | None = None) -> None:
    """Run ``alembic upgrade <target>`` against ``db_url`` via the canonical ini.

    On ``--dry-run`` it prints ``current`` + the offline ``upgrade --sql`` plan
    instead of executing. ``extra_env`` injects the ``PENNY_*`` vars the contract
    migrations read (e.g. ``PENNY_DEV_HOUSEHOLD_ID`` so 016 backfills categories,
    ``PENNY_PLAID_TOKEN_KEY`` so 017 encrypts) — deliberately WITHOUT
    ``PENNY_DEV_BACKFILL`` so 013 stays a prod no-op.
    """
    env = {**os.environ, "DATABASE_URL": db_url, **(extra_env or {})}
    base = ["alembic", "-c", str(ALEMBIC_INI)]
    if dry_run:
        echo(f"[dry-run] alembic current for {_redact(db_url)}:")
        subprocess.run([*base, "current"], env=env, check=False)
        echo(f"[dry-run] offline SQL plan for `upgrade {target}`:")
        subprocess.run([*base, "upgrade", "--sql", target], env=env, check=False)
        return
    echo(f"Running: alembic upgrade {target}")
    subprocess.run([*base, "upgrade", target], env=env, check=True)


def alembic_stamp(db_url: str, revision: str, *, dry_run: bool) -> None:
    """``alembic stamp`` — record ``revision`` as applied without running it.

    Used to reconcile prod's ``create_all``-managed baseline: prod's schema
    already matches the models at ``BASELINE_REVISION``, so we stamp it before
    upgrading rather than trying to re-run migrations 000-009 against an
    already-populated schema.

    Uses ``--purge`` to unconditionally erase ``alembic_version`` before
    stamping. Prod's live ``create_all``-managed app records a *legacy* head
    (e.g. ``013_partial_unique_category_key``) that does not exist in this
    branch's script directory; a plain ``stamp`` would abort trying to locate
    that current revision. ``--purge`` ignores it and writes the baseline
    cleanly — the same fresh start a forked clone gets.
    """
    env = {**os.environ, "DATABASE_URL": db_url}
    base = ["alembic", "-c", str(ALEMBIC_INI)]
    if dry_run:
        echo(f"[dry-run] would `alembic stamp --purge {revision}`")
        return
    echo(f"Running: alembic stamp --purge {revision}")
    subprocess.run([*base, "stamp", "--purge", revision], env=env, check=True)


def alembic_heads(db_url: str) -> str:
    """Capture ``alembic current`` output (the recorded head[s]) for reporting.

    A create_all-managed prod historically carried divergent legacy heads; the
    repo already folds them at revision 008, so reconcile inspects the recorded
    head here to decide whether a stamp is needed."""
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), "current"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout + result.stderr).strip()


# --------------------------------------------------------------------------- #
# Console                                                                     #
# --------------------------------------------------------------------------- #


def echo(msg: str) -> None:
    print(msg, flush=True)


def _redact(url: str) -> str:
    """Hide credentials when echoing a DB URL."""
    if "@" in url and "://" in url:
        scheme, _, rest = url.partition("://")
        _, _, host = rest.partition("@")
        return f"{scheme}://***@{host}"
    return url


def require(condition: bool, message: str) -> None:
    """Abort loudly (non-zero exit) when a precondition fails — the cutover never
    limps forward on a broken invariant."""
    if not condition:
        echo(f"ABORT: {message}")
        sys.exit(1)
