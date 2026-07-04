"""Bootstrap creates the schema and seeds the taxonomy exactly once."""

from __future__ import annotations

import pytest

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


def test_bootstrap_fails_clearly_on_pre_tenancy_database(
    isolated_db, tmp_path, monkeypatch
):
    # A dev penny.db from before phase 1a lacks the tenant columns, and
    # create_all can never ALTER them in — bootstrap must say so up front
    # instead of dying later with an obscure OperationalError.
    import sqlalchemy as sa

    db_path = tmp_path / "stale.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE categories (category_id INTEGER PRIMARY KEY, key TEXT)"
            )
        )
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import penny.db

    penny.db._db = None
    with pytest.raises(RuntimeError, match="pre-tenancy|household_id"):
        bootstrap()
    penny.db._db = None
