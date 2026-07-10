"""First-run bootstrap: create tables, seed the taxonomy.

Idempotent. Safe to call on every backend startup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import uuid

from loguru import logger
from sqlalchemy.orm import Session
import yaml

from .adapters.db.models import Category, Household, User
from .db import get_db

_TAXONOMY_YAML = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"


def bootstrap() -> None:
    """Ensure schema + seed the dev identity.

    SQLite (dev/test) builds the schema from the models via ``create_all``.
    On Postgres the schema is owned by alembic and applied out of band by
    ``penny migrate`` (the deploy ``release_command``), so bootstrap creates
    nothing there — it only seeds, which is a no-op on prod (no ``PENNY_DEV_*``).
    """
    db = get_db()
    if db.dialect == "sqlite":
        db.create_schema()
        # Website-owned conversation store: a SEPARATE engine + schema/DB from
        # the finance tables above (see api/persistence/engine.py). On Postgres
        # its web.* tables are created by the same alembic chain (migration 019).
        from .api.persistence.engine import create_web_schema

        create_web_schema()
    _seed_dev_household()


def _seed_dev_household() -> None:
    """Ensure the PENNY_DEV_* principal exists and has a taxonomy.

    Categories are per-household, so seeding needs a household to seed *for*.
    In dev that is the env-pinned principal; with no PENNY_DEV_* configured
    (e.g. prod, where identity comes from the phase-3 cutover / phase-2 auth)
    this is a no-op.
    """
    household_raw = os.environ.get("PENNY_DEV_HOUSEHOLD_ID", "").strip()
    user_raw = os.environ.get("PENNY_DEV_USER_ID", "").strip()
    if not household_raw or not user_raw:
        logger.debug("PENNY_DEV_* principal not configured; skipping taxonomy seed.")
        return
    household_id = uuid.UUID(household_raw)
    user_id = uuid.UUID(user_raw)
    email = os.environ.get("PENNY_DEV_USER_EMAIL", "").strip() or "dev@example.com"

    db = get_db()
    from .tenancy.context import RequestContext

    # session_for pins the household so the inserts pass RLS WITH CHECK on
    # Postgres (categories carry a household-only policy).
    ctx = RequestContext(user_id=user_id, household_id=household_id)
    with db.session_for(ctx) as session:
        if session.get(Household, household_id) is None:
            session.add(Household(household_id=household_id, name="Dev Household"))
            session.flush()
        if session.get(User, user_id) is None:
            session.add(User(user_id=user_id, household_id=household_id, email=email))
            session.flush()
        seed_taxonomy_for_household(session, household_id)


def seed_taxonomy_for_household(session: Session, household_id: uuid.UUID) -> None:
    """Seed the YAML taxonomy for ``household_id`` if it has no categories."""
    if not _TAXONOMY_YAML.exists():
        logger.warning(
            "Taxonomy YAML missing at {} — skipping seed. Run `uv run "
            "python scripts/sync_taxonomy_from_supabase.py` to fetch.",
            _TAXONOMY_YAML,
        )
        return

    existing = session.query(Category).filter_by(household_id=household_id).count()
    if existing > 0:
        logger.debug(
            "Household {} already has {} categories; skip seed.",
            household_id,
            existing,
        )
        return

    raw = yaml.safe_load(_TAXONOMY_YAML.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        logger.error("taxonomy.yaml is not a list of category rows; got {}", type(raw))
        return

    # Two passes: parents first (so children's parent_id resolves).
    by_key: dict[str, Category] = {}
    for row in raw:
        if row.get("parent_key") is None:
            cat = _row_to_category(row, parent_id=None, household_id=household_id)
            session.add(cat)
            session.flush()
            by_key[cat.key] = cat
    for row in raw:
        parent_key = row.get("parent_key")
        if parent_key is None:
            continue
        parent = by_key.get(parent_key)
        if parent is None:
            logger.warning(
                "Skipping {!r} — parent {!r} not found", row.get("key"), parent_key
            )
            continue
        cat = _row_to_category(
            row, parent_id=parent.category_id, household_id=household_id
        )
        session.add(cat)
    session.flush()
    logger.info(
        "Seeded {} categories for household {} from {}",
        session.query(Category).filter_by(household_id=household_id).count(),
        household_id,
        _TAXONOMY_YAML,
    )


def _row_to_category(
    row: dict[str, Any], *, parent_id: int | None, household_id: uuid.UUID
) -> Category:
    return Category(
        key=row["key"],
        name=row["name"],
        parent_id=parent_id,
        household_id=household_id,
        description=row.get("description"),
        rules=row.get("rules"),
    )
