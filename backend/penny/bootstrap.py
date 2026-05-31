"""First-run bootstrap: create tables, seed the taxonomy.

Idempotent. Safe to call on every backend startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .adapters.db.models import Category
from .db import get_db

_TAXONOMY_YAML = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"


def bootstrap() -> None:
    """Create schema if missing, seed categories if the table is empty."""
    db = get_db()
    db.create_schema()
    _seed_taxonomy_if_empty()


def _seed_taxonomy_if_empty() -> None:
    db = get_db()
    if not _TAXONOMY_YAML.exists():
        logger.warning(
            "Taxonomy YAML missing at {} — skipping seed. Run `uv run "
            "python scripts/sync_taxonomy_from_supabase.py` to fetch.",
            _TAXONOMY_YAML,
        )
        return

    with db.session() as session:
        existing = session.query(Category).count()
        if existing > 0:
            logger.debug("Categories table already has {} rows; skip seed.", existing)
            return

        raw = yaml.safe_load(_TAXONOMY_YAML.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            logger.error("taxonomy.yaml is not a list of category rows; got {}", type(raw))
            return

        # Two passes: parents first (so children's parent_id resolves).
        by_key: dict[str, Category] = {}
        for row in raw:
            if row.get("parent_key") is None:
                cat = _row_to_category(row, parent_id=None)
                session.add(cat)
                session.flush()
                by_key[cat.key] = cat
        for row in raw:
            parent_key = row.get("parent_key")
            if parent_key is None:
                continue
            parent = by_key.get(parent_key)
            if parent is None:
                logger.warning("Skipping {!r} — parent {!r} not found", row.get("key"), parent_key)
                continue
            cat = _row_to_category(row, parent_id=parent.category_id)
            session.add(cat)
        session.commit()
        logger.info("Seeded {} categories from {}", session.query(Category).count(), _TAXONOMY_YAML)


def _row_to_category(row: dict[str, Any], *, parent_id: int | None) -> Category:
    return Category(
        key=row["key"],
        name=row["name"],
        parent_id=parent_id,
        description=row.get("description"),
        rules=row.get("rules"),
    )
