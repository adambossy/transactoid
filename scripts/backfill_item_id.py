#!/usr/bin/env python3
"""Backfill item_id on plaid_transactions by querying Plaid API.

This script:
1. Fetches all PlaidItems from the database
2. For each item, calls Plaid API to get its accounts
3. Updates plaid_transactions where account_id matches

Run after applying migration 005_add_item_id_to_plaid_transactions.

Usage:
    uv run python scripts/backfill_item_id.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from transactoid.adapters.clients.plaid import (  # noqa: E402
    PlaidClient,
    PlaidClientError,
)
from transactoid.adapters.db.facade import DB  # noqa: E402


def backfill_item_ids(*, dry_run: bool = False) -> None:
    """Backfill item_id column on plaid_transactions."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)
    plaid_client = PlaidClient.from_env()

    # Get all PlaidItems
    plaid_items = db.list_plaid_items()
    if not plaid_items:
        print("No PlaidItems found in database.")
        return

    print(f"Found {len(plaid_items)} PlaidItem(s)")

    # Build account_id -> item_id mapping
    account_to_item: dict[str, str] = {}
    errors: list[str] = []

    for item in plaid_items:
        print(f"\nFetching accounts for {item.institution_name or item.item_id}...")
        try:
            accounts = plaid_client.get_accounts(item.access_token)
            for account in accounts:
                account_id = account["account_id"]
                account_to_item[account_id] = item.item_id
                acc_short = account_id[:8]
                item_short = item.item_id[:8]
                print(f"  - {account['name']} ({acc_short}...) -> {item_short}...")
        except PlaidClientError as e:
            errors.append(f"  Failed to fetch accounts for {item.item_id}: {e}")
            print(f"  ERROR: {e}")

    if not account_to_item:
        print("\nNo account mappings found. Cannot proceed.")
        if errors:
            print("\nErrors encountered:")
            for err in errors:
                print(err)
        return

    print(f"\nBuilt mapping for {len(account_to_item)} account(s)")

    # Get distinct account_ids from plaid_transactions
    with db._engine.connect() as conn:
        query = text(
            "SELECT DISTINCT account_id FROM plaid_transactions WHERE item_id IS NULL"
        )
        result = conn.execute(query)
        unmapped_accounts: list[str] = [row[0] for row in result]

    print(f"Found {len(unmapped_accounts)} distinct account_id(s) needing backfill")

    # Update plaid_transactions
    updated_count = 0
    orphaned_accounts: list[str] = []

    for account_id in unmapped_accounts:
        item_id = account_to_item.get(account_id)
        if item_id is None:
            orphaned_accounts.append(account_id)
            continue

        acc_short = account_id[:8]
        item_short = item_id[:8]
        if dry_run:
            print(f"  [DRY RUN] Would update {acc_short}... -> {item_short}...")
        else:
            with db._engine.begin() as conn:
                update_sql = text(
                    "UPDATE plaid_transactions "
                    "SET item_id = :item_id WHERE account_id = :account_id"
                )
                result = conn.execute(
                    update_sql,
                    {"item_id": item_id, "account_id": account_id},
                )
                updated_count += result.rowcount
                rows = result.rowcount
                print(f"  Updated {rows} row(s): {acc_short}... -> {item_short}...")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    if dry_run:
        num_accounts = len(account_to_item)
        print(f"[DRY RUN] Would update transactions for {num_accounts} account(s)")
    else:
        print(f"Updated {updated_count} transaction(s)")

    if orphaned_accounts:
        num_orphaned = len(orphaned_accounts)
        print(f"\nWARNING: {num_orphaned} account(s) have no matching PlaidItem:")
        for acc in orphaned_accounts:
            # Count transactions for this orphaned account
            with db._engine.connect() as conn:
                count_sql = text(
                    "SELECT COUNT(*) FROM plaid_transactions "
                    "WHERE account_id = :account_id"
                )
                result = conn.execute(count_sql, {"account_id": acc})
                count = result.scalar()
            print(f"  - {acc} ({count} transaction(s))")
        print("\nThese transactions belong to a deleted PlaidItem.")
        print("To clean them up, you can run:")
        print("  DELETE FROM plaid_transactions WHERE item_id IS NULL;")

    if errors:
        print("\nErrors encountered:")
        for err in errors:
            print(err)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill item_id on plaid_transactions from Plaid API"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    try:
        backfill_item_ids(dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
