#!/usr/bin/env python3
"""Clean up plaid_transactions for a specific account by name.

Usage:
    uv run python scripts/cleanup_orphaned_transactions.py --dry-run
    uv run python scripts/cleanup_orphaned_transactions.py
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

TARGET_ACCOUNT_NAME = "CORP Account - JOIA"


def cleanup_transactions(*, dry_run: bool = False) -> None:
    """Delete plaid_transactions for TARGET_ACCOUNT_NAME."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)
    plaid_client = PlaidClient.from_env()

    # Look up active Plaid accounts
    plaid_items = db.list_plaid_items()
    target_account_id: str | None = None

    for item in plaid_items:
        try:
            accounts = plaid_client.get_accounts(item.access_token)
            for account in accounts:
                if account["name"] == TARGET_ACCOUNT_NAME:
                    target_account_id = account["account_id"]
                    print(f"Found '{TARGET_ACCOUNT_NAME}' -> {target_account_id}")
                    break
        except PlaidClientError as e:
            print(f"Warning: Failed to fetch accounts for {item.item_id}: {e}")
        if target_account_id:
            break

    if not target_account_id:
        print(f"Account '{TARGET_ACCOUNT_NAME}' not found. Nothing to do.")
        return

    # Count and delete
    with db._engine.connect() as conn:
        count_sql = text(
            "SELECT COUNT(*) FROM plaid_transactions WHERE account_id = :account_id"
        )
        result = conn.execute(count_sql, {"account_id": target_account_id})
        count = result.scalar()

    print(f"Found {count} plaid_transactions to delete")

    if count == 0:
        return

    if dry_run:
        print(f"[DRY RUN] Would delete {count} plaid_transactions")
        return

    with db._engine.begin() as conn:
        delete_sql = text(
            "DELETE FROM plaid_transactions WHERE account_id = :account_id"
        )
        result = conn.execute(delete_sql, {"account_id": target_account_id})
        print(f"Deleted {result.rowcount} plaid_transactions")


def main() -> None:
    desc = f"Delete transactions for '{TARGET_ACCOUNT_NAME}'"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    cleanup_transactions(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
