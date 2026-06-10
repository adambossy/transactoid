"""Seed account_sign_conventions from the empirical institution mapping.

For each distinct account_id in plaid_transactions, looks up the institution
name and maps it to 'expense_positive' or 'expense_negative'. Accounts whose
institution is NULL or unknown get the default 'expense_positive'.

Accounts that already have a row in account_sign_conventions are left
unchanged (ON CONFLICT DO NOTHING semantics). Re-running is safe.

Usage:
    DATABASE_URL=postgresql://... \\
        uv run python scripts/seed_sign_conventions.py
    DATABASE_URL=postgresql://... \\
        uv run python scripts/seed_sign_conventions.py --dry-run
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from penny.adapters.db.facade import DB  # noqa: E402
from penny.adapters.db.sign_convention_defaults import (  # noqa: E402
    INSTITUTION_SIGN_CONVENTIONS,
)


def seed_sign_conventions(*, dry_run: bool = False) -> dict[str, int]:
    """Seed account_sign_conventions from the institution mapping.

    Args:
        dry_run: If True, prints planned insertions without writing to DB.

    Returns:
        Counts: {"inserted": N, "skipped_existing": M, "default_applied": K}.
        In dry-run mode, 'inserted' reflects what would be inserted.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)
    counts = db.seed_sign_conventions_from_institutions(
        INSTITUTION_SIGN_CONVENTIONS, dry_run=dry_run
    )

    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}Done. "
        f"inserted={counts['inserted']}, "
        f"skipped_existing={counts['skipped_existing']}, "
        f"default_applied={counts['default_applied']}"
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed account_sign_conventions from institution mapping"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without making changes",
    )
    args = parser.parse_args()

    seed_sign_conventions(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
