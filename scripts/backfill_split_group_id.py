#!/usr/bin/env python3
"""Backfill split_group_id, split_source, and split_index on Amazon-derived rows.

Amazon-derived transactions share a ``plaid_transaction_id`` when one Plaid
transaction was split into N item-level rows by ``AmazonMutationPlugin``.
This script groups such rows and stamps them with a shared ``split_group_id``
UUID, ``split_source='amazon_mutation'``, and a stable ``split_index`` ordered
by ``external_id``.

Rows that already have ``split_group_id`` set are skipped (idempotent).
Plaid transactions that map to only a single derived row are also skipped —
there is nothing to group.

Usage:
    DATABASE_URL=sqlite:///transactoid.db \
        uv run python scripts/backfill_split_group_id.py
    DATABASE_URL=sqlite:///transactoid.db \
        uv run python scripts/backfill_split_group_id.py --dry-run
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import os
from pathlib import Path
import sys
import uuid

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from transactoid.adapters.db.facade import DB  # noqa: E402
from transactoid.adapters.db.models import DerivedTransaction  # noqa: E402


def backfill_split_group_ids(*, dry_run: bool = False) -> dict[str, int]:
    """Backfill split provenance columns on Amazon-derived rows.

    Groups derived rows that share a ``plaid_transaction_id`` (and where not
    all rows in the group already have ``split_group_id`` set) and assigns a
    new UUID plus ``split_source='amazon_mutation'`` and ``split_index`` based
    on sorted ``external_id`` order.

    Args:
        dry_run: If True, prints planned changes without writing to DB.

    Returns:
        Dict with keys ``groups_updated`` and ``rows_updated`` (counts rows that
        would be, or were, updated — depending on dry_run).
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    db = DB(db_url)

    with db.session() as session:
        # Load all derived transactions that share a plaid_transaction_id with
        # at least one sibling (i.e. multi-row groups).
        all_derived = session.query(DerivedTransaction).all()

        # Group by plaid_transaction_id.
        by_plaid: dict[int, list[DerivedTransaction]] = defaultdict(list)
        for row in all_derived:
            by_plaid[row.plaid_transaction_id].append(row)

        groups_updated = 0
        rows_updated = 0

        for plaid_id, group in by_plaid.items():
            if len(group) < 2:
                # Only one derived row for this plaid txn — not a split.
                continue

            # Skip groups where every row is already stamped.
            all_rows_stamped = all(row.split_group_id is not None for row in group)
            if all_rows_stamped:
                continue

            # Sort by external_id for a stable split_index assignment.
            sorted_group = sorted(group, key=lambda r: r.external_id)
            new_split_group_id = str(uuid.uuid4())

            print(
                f"{'[DRY RUN] ' if dry_run else ''}"
                f"plaid_txn {plaid_id}: grouping {len(sorted_group)} rows "
                f"-> split_group_id={new_split_group_id}"
            )

            for split_index, row in enumerate(sorted_group):
                # Per-row idempotency: skip rows already stamped (e.g. user splits).
                if row.split_group_id is not None:
                    continue
                if row.is_verified:
                    print(
                        f"WARNING: row {row.transaction_id} is verified; skipping",
                        file=sys.stderr,
                    )
                    continue
                print(
                    f"  {'[DRY RUN] ' if dry_run else ''}"
                    f"row {row.transaction_id} external_id={row.external_id!r} "
                    f"split_index={split_index}"
                )
                if not dry_run:
                    row.split_group_id = new_split_group_id
                    row.split_source = "amazon_mutation"
                    row.split_index = split_index
                rows_updated += 1

            groups_updated += 1

        if not dry_run:
            # Session commits on context-manager exit; flush here to surface errors.
            session.flush()

    mode = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode}Done. groups_updated={groups_updated}, rows_updated={rows_updated}")
    return {"groups_updated": groups_updated, "rows_updated": rows_updated}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill split_group_id/split_source/split_index on Amazon-derived rows"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    backfill_split_group_ids(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
