#!/usr/bin/env python3
"""Re-derive all unverified rows for expense_negative accounts.

One-shot backfill. Existing rows for accounts whose institution uses the
inverted sign convention (BofA, Alliant per seed mapping) carry bank-sign
amounts in derived_transactions. This script re-derives them through PR
#13's normalization so they reflect the canonical expense=positive
convention.

Idempotent at the data level: re-running on already-canonical rows produces
an equivalent result (delete and reinsert with the same amounts; row IDs
will differ but no observable data change).

Verified rows are NOT touched (per the user's "rederive only unverified
rows" rule). The script prints a summary of preserved verified rows per
account; those require manual intervention or a future
--include-verified flag.

Usage:
    DATABASE_URL=sqlite:///transactoid.db \\
        uv run python scripts/backfill_sign_conventions.py
    DATABASE_URL=sqlite:///transactoid.db \\
        uv run python scripts/backfill_sign_conventions.py --dry-run
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from transactoid.adapters.db.facade import DB  # noqa: E402
from transactoid.services.re_derive import (  # noqa: E402
    ReDeriveResult,
    SupportsReDerive,
    re_derive_account,
)


def _count_unverified_for_account(db: DB, account_id: str) -> int:
    """Return the number of unverified derived rows for the given account."""
    plaid_ids = db.list_plaid_transaction_ids_for_account(account_id)
    if not plaid_ids:
        return 0
    derived_map = db.get_derived_by_plaid_ids(plaid_ids)
    return sum(
        1 for rows in derived_map.values() for row in rows if not row.is_verified
    )


def backfill_sign_conventions(
    *,
    dry_run: bool = False,
    sync_tool_factory: Callable[[DB], SupportsReDerive] | None = None,
) -> dict[str, int]:
    """Re-derive unverified derived rows for all expense_negative accounts.

    Args:
        dry_run: If True, lists which accounts would be re-derived and how
            many unverified rows each has, without making any changes.
        sync_tool_factory: Optional factory for the mutation/categorize runner.
            Defaults to a real SyncTool. Provided for testing.

    Returns:
        Aggregate counts: {
            "accounts_processed": N,
            "accounts_failed": M,
            "total_deleted": K,
            "total_new_derived": L,
            "total_verified_skipped": P,
        }.
        In dry-run mode, 'total_deleted' reflects what would be re-derived
        (unverified row count) and 'total_new_derived' is 0.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)

    conventions = db.list_sign_conventions()
    expense_negative = [
        c for c in conventions if c.sign_convention == "expense_negative"
    ]

    if not expense_negative:
        print("No expense_negative accounts found. Nothing to do.")
        return {
            "accounts_processed": 0,
            "accounts_failed": 0,
            "total_deleted": 0,
            "total_new_derived": 0,
            "total_verified_skipped": 0,
        }

    if dry_run:
        print("[DRY RUN] The following accounts would be re-derived:")

    accounts_processed = 0
    accounts_failed = 0
    total_deleted = 0
    total_new_derived = 0
    total_verified_skipped = 0

    any_failure = False

    for convention in expense_negative:
        account_id = convention.account_id

        if dry_run:
            plaid_ids = db.list_plaid_transaction_ids_for_account(account_id)
            if not plaid_ids:
                print(f"  account_id={account_id!r}: 0 plaid transactions, skipping")
                continue
            unverified_count = _count_unverified_for_account(db, account_id)
            derived_map = db.get_derived_by_plaid_ids(plaid_ids)
            verified_count = sum(
                1 for rows in derived_map.values() for row in rows if row.is_verified
            )
            print(
                f"  account_id={account_id!r}: "
                f"would re-derive {unverified_count} unverified rows "
                f"(verified_preserved={verified_count})"
            )
            total_deleted += unverified_count
            total_verified_skipped += verified_count
            accounts_processed += 1
            continue

        try:
            result: ReDeriveResult = re_derive_account(
                db,
                account_id,
                sync_tool_factory=sync_tool_factory,
            )
        except ValueError as exc:
            print(
                f"ERROR: account_id={account_id!r} raised: {exc}",
                file=sys.stderr,
            )
            accounts_failed += 1
            any_failure = True
            continue

        if result.mutate_failed or result.categorize_failed:
            failure_stage = "mutate" if result.mutate_failed else "categorize"
            print(
                f"ERROR: account_id={account_id!r} {failure_stage} failed: "
                f"{result.failure_message}",
                file=sys.stderr,
            )
            print(
                "  Recovery: inspect the account and re-run "
                "`scripts/backfill_sign_conventions.py` after fixing the issue.",
                file=sys.stderr,
            )
            accounts_failed += 1
            any_failure = True
            continue

        total_deleted += result.deleted_count
        total_new_derived += result.new_derived_count
        total_verified_skipped += result.verified_skipped
        accounts_processed += 1

        preserved_note = (
            f", verified_preserved={result.verified_skipped}"
            if result.verified_skipped
            else ""
        )
        print(
            f"account_id={account_id!r}: "
            f"re-derived {result.new_derived_count} rows "
            f"(deleted={result.deleted_count}{preserved_note})"
        )

    mode = "[DRY RUN] " if dry_run else ""
    print(
        f"\n{mode}Done. "
        f"accounts_processed={accounts_processed}, "
        f"accounts_failed={accounts_failed}, "
        f"total_deleted={total_deleted}, "
        f"total_new_derived={total_new_derived}, "
        f"total_verified_skipped={total_verified_skipped}"
    )

    if any_failure:
        sys.exit(1)

    return {
        "accounts_processed": accounts_processed,
        "accounts_failed": accounts_failed,
        "total_deleted": total_deleted,
        "total_new_derived": total_new_derived,
        "total_verified_skipped": total_verified_skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-derive unverified rows for expense_negative accounts"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which accounts would be re-derived without making changes",
    )
    args = parser.parse_args()

    backfill_sign_conventions(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
