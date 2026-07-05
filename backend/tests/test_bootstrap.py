"""Bootstrap creates the schema and seeds the taxonomy exactly once."""

from __future__ import annotations

from penny.adapters.db.models import Category
from penny.bootstrap import bootstrap
from penny.db import get_db


def _category_count() -> int:
    with get_db().session() as session:
        return session.query(Category).count()


def test_bootstrap_seeds_taxonomy_idempotently(isolated_db, monkeypatch):
    # Taxonomy is per-household; bootstrap seeds for the env-pinned dev
    # principal (no PENNY_DEV_* -> no-op, e.g. prod).
    monkeypatch.setenv("PENNY_DEV_USER_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("PENNY_DEV_HOUSEHOLD_ID", "22222222-2222-2222-2222-222222222222")
    bootstrap()
    seeded = _category_count()

    bootstrap()
    output = _category_count()

    assert seeded > 0
    assert output == seeded


def test_bootstrap_without_dev_principal_skips_seed(isolated_db, monkeypatch):
    monkeypatch.delenv("PENNY_DEV_USER_ID", raising=False)
    monkeypatch.delenv("PENNY_DEV_HOUSEHOLD_ID", raising=False)
    bootstrap()
    assert _category_count() == 0
