#!/usr/bin/env python3
"""Script to list and remove duplicate Plaid items."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from transactoid.adapters.db.facade import DB

# Load environment
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def list_items(db: DB) -> None:
    """List all Plaid items with details."""
    items = db.list_plaid_items()

    if not items:
        print("No Plaid items found.")
        return

    print(f"\nFound {len(items)} Plaid item(s):\n")
    for idx, item in enumerate(items, 1):
        print(f"{idx}. Item ID: {item.item_id}")
        print(f"   Institution: {item.institution_name or '(unknown)'}")
        print(f"   Institution ID: {item.institution_id or '(unknown)'}")
        print(f"   Created: {item.created_at}")
        print(f"   Sync cursor: {'Set' if item.sync_cursor else 'Not set'}")
        print()


def delete_item(db: DB, item_id: str) -> None:
    """Delete a Plaid item by ID."""
    # Verify item exists first
    item = db.get_plaid_item(item_id)
    if not item:
        print(f"Error: Item {item_id} not found.", file=sys.stderr)
        sys.exit(1)

    print("About to delete:")
    print(f"  Item ID: {item.item_id}")
    print(f"  Institution: {item.institution_name or '(unknown)'}")
    print("\nThis will also delete all associated transactions (CASCADE).")

    confirm = input("\nAre you sure? Type 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        sys.exit(0)

    # Delete the item
    success = db.delete_plaid_item(item_id)
    if success:
        print(f"\n✓ Successfully deleted item {item_id}")
    else:
        print(f"\n✗ Failed to delete item {item_id}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set in environment.", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/remove_duplicate_item.py list")
        print("  python scripts/remove_duplicate_item.py delete <item_id>")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        list_items(db)
    elif command == "delete":
        if len(sys.argv) < 3:
            print("Error: Missing item_id argument.", file=sys.stderr)
            print("Usage: python scripts/remove_duplicate_item.py delete <item_id>")
            sys.exit(1)
        item_id = sys.argv[2]
        delete_item(db, item_id)
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Valid commands: list, delete")
        sys.exit(1)


if __name__ == "__main__":
    main()
