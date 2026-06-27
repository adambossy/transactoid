"""Build / hydrate the per-run SQLite fixture.

At the end of an eval run the disposable Neon branch is copied into a single
SQLite file (the categorizer-reachable tables only), gzipped, and uploaded to R2;
the branch is then deleted. A backtest later hydrates that fixture into a
throwaway SQLite DB and replays the categorizer against the exact frozen input +
history.

The copy goes table-by-table through the shared SQLAlchemy models (NOT pg_dump),
so column types and CHECK constraints stay dialect-correct between Postgres and
SQLite. SQLite is dev-only in Penny, so backtests carry a minor fidelity caveat
vs. the Postgres run — acceptable for a non-production backtest.
"""

from __future__ import annotations

import gzip
from pathlib import Path
import tempfile

from sqlalchemy import insert, select

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    Category,
    DerivedTransaction,
    Merchant,
    PlaidItem,
    PlaidTransaction,
    Tag,
    TransactionCategoryEvent,
    TransactionTag,
)

# Categorizer-reachable tables + their referential closure, in FK-safe insert
# order. (FK enforcement is off on the fixture DB, but a sensible order keeps the
# file clean and makes the closure explicit.)
_FIXTURE_MODELS = (
    Category,
    Merchant,
    PlaidItem,
    PlaidTransaction,
    DerivedTransaction,
    TransactionCategoryEvent,
    Tag,
    TransactionTag,
)


def _copy_tables(src_db: DB, dst_db: DB) -> None:
    for model in _FIXTURE_MODELS:
        table = model.__table__
        with src_db.session() as session:
            rows = [
                dict(row) for row in session.execute(select(table)).mappings().all()
            ]
        if rows:
            with dst_db.session() as session:
                session.execute(insert(table), rows)


def build_sqlite_fixture_bytes(src_db: DB) -> bytes:
    """Copy the reachable tables of ``src_db`` into a SQLite file; return gzip bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.sqlite"
        dst_db = DB(f"sqlite:///{path}", enforce_sqlite_fks=False)
        dst_db.create_schema()
        _copy_tables(src_db, dst_db)
        raw = path.read_bytes()
    return gzip.compress(raw)


def hydrate_fixture(gzipped: bytes, dst_path: str | Path) -> DB:
    """Write a gzipped fixture to ``dst_path`` and open it as a DB (for backtests)."""
    Path(dst_path).write_bytes(gzip.decompress(gzipped))
    return DB(f"sqlite:///{dst_path}", enforce_sqlite_fks=False)
