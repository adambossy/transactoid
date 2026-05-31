"""Lazy DB singleton.

The agent-facing tools and the bootstrap step share one ``DB`` instance per
process. URL comes from ``$DATABASE_URL`` (defaults to a local SQLite file
at ``./penny.db`` for dev).
"""

from __future__ import annotations

import os

from .adapters.db.facade import DB

_DEFAULT_URL = "sqlite:///./penny.db"

_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        url = os.environ.get("DATABASE_URL", "").strip() or _DEFAULT_URL
        _db = DB(url, enforce_sqlite_fks=url.startswith("sqlite"))
    return _db
