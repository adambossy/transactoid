"""Apply category descriptions from configs/taxonomy.yaml to a populated DB.

`bootstrap` only seeds the categories table when it is empty, so once a database
is live the YAML's `description` field never reaches it. This script pushes the
descriptions (and only the descriptions) into the existing `categories` rows,
matched by `key`. It is the apply step for the description backfill: edit the
YAML, then run this against the target DB.

Safe by design:
- Dry-run by default; pass ``--apply`` to write.
- Updates ONLY `description` on active rows matched by `key`. It never inserts,
  deletes, deprecates, renames, or reparents — unlike
  `replace_categories_from_taxonomy`.
- Reports drift (keys in the YAML missing from the DB, and active DB keys absent
  from the YAML) without acting on it.

Target DB is whatever ``DATABASE_URL`` points at, so set the environment
deliberately (e.g. ``set -a && source .env.test && set +a``) before running.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from loguru import logger
import yaml

from penny.adapters.db.models import Category
from penny.db import get_db

_TAXONOMY_YAML = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without it, the script only reports what would change.",
    )
    args = parser.parse_args()

    rows = yaml.safe_load(_TAXONOMY_YAML.read_text(encoding="utf-8"))
    yaml_desc = {r["key"]: r.get("description") for r in rows}

    db = get_db()
    changed: list[str] = []
    missing_in_db: list[str] = []
    with db.session() as session:
        active = {
            c.key: c
            for c in session.query(Category).filter(Category.deprecated_at.is_(None))
        }
        for key, desc in yaml_desc.items():
            cat = active.get(key)
            if cat is None:
                missing_in_db.append(key)
                continue
            if cat.description != desc:
                changed.append(key)
                if args.apply:
                    cat.description = desc
        db_only = sorted(set(active) - set(yaml_desc))
        if not args.apply:
            session.rollback()

    logger.info("{} active DB categories; YAML has {}", len(active), len(yaml_desc))
    logger.info(
        "{} descriptions {}", len(changed), "updated" if args.apply else "would change"
    )
    for key in changed:
        logger.debug("  changed: {}", key)
    if missing_in_db:
        logger.warning(
            "{} YAML keys absent from DB (skipped): {}",
            len(missing_in_db),
            missing_in_db,
        )
    if db_only:
        logger.warning(
            "{} active DB keys absent from YAML (untouched): {}", len(db_only), db_only
        )
    if not args.apply:
        logger.info("Dry run — re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
