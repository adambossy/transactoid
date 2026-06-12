"""The website store's own engine + schema creation.

Separate from the finance ``penny.adapters.db`` engine so conversation data
lives in a different database/schema than the finance tables:

- **Dev (SQLite):** a separate file ``penny_web.db`` next to the finance
  ``penny.db``. SQLite has no schemas, so the logical ``web`` schema on the
  models is translated to ``None``.
- **Prod (Postgres/Neon):** the same Postgres server as the finance DB but a
  dedicated ``web`` schema. The logical ``web`` schema is translated to the
  real ``web`` schema, which is created if missing before ``create_all``.

Override the URL with ``$PENNY_WEB_DATABASE_URL``; otherwise it is derived from
``$DATABASE_URL`` (the finance URL).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import WEB_SCHEMA, WebBase

_FINANCE_DEFAULT_URL = "sqlite:///./penny.db"
_WEB_SQLITE_DEFAULT_URL = "sqlite:///./penny_web.db"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def resolve_web_url() -> str:
    """Resolve the website store's database URL.

    Priority: ``$PENNY_WEB_DATABASE_URL`` > derived from ``$DATABASE_URL`` >
    the SQLite default. For a SQLite finance URL we point at a *separate* file;
    for a Postgres finance URL we reuse the same server (the ``web`` schema
    provides the separation).
    """
    explicit = os.environ.get("PENNY_WEB_DATABASE_URL", "").strip()
    if explicit:
        return explicit

    finance_url = os.environ.get("DATABASE_URL", "").strip() or _FINANCE_DEFAULT_URL
    if _is_sqlite(finance_url):
        return _WEB_SQLITE_DEFAULT_URL
    # Postgres: reuse the same database; the ``web`` schema separates the data.
    return finance_url


class _WebEngine:
    """Lazy holder for the website store's engine + session factory."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    def _build(self) -> None:
        url = resolve_web_url()
        engine_kwargs: dict[str, object] = {"echo": False}
        if not _is_sqlite(url):
            engine_kwargs.update({"pool_pre_ping": True, "pool_recycle": 300})
        engine = create_engine(url, **engine_kwargs)
        # Translate the models' logical ``web`` schema: real schema on
        # Postgres, ``None`` (no schema) on SQLite.
        schema = None if _is_sqlite(url) else WEB_SCHEMA
        engine = engine.execution_options(schema_translate_map={WEB_SCHEMA: schema})
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, class_=Session)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._build()
        if self._engine is None:  # pragma: no cover - _build always sets it
            raise RuntimeError("web engine failed to initialize")
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._build()
        if self._session_factory is None:  # pragma: no cover
            raise RuntimeError("web session factory failed to initialize")
        return self._session_factory

    def reset(self) -> None:
        """Drop the cached engine (used by tests to repoint the URL)."""
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None


_web_engine = _WebEngine()


def get_web_engine() -> Engine:
    """Return the process-wide website-store engine (lazy)."""
    return _web_engine.engine


def get_web_session_factory() -> sessionmaker[Session]:
    """Return the website-store session factory (lazy)."""
    return _web_engine.session_factory


def reset_web_engine() -> None:
    """Reset the cached engine — for tests that repoint the URL."""
    _web_engine.reset()


def create_web_schema() -> None:
    """Create the website store's tables (and the ``web`` schema on Postgres).

    Idempotent. ``create_all`` only creates missing tables; the Postgres
    ``web`` schema is created first so the qualified table names resolve.
    """
    engine = get_web_engine()
    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {WEB_SCHEMA}"))
    WebBase.metadata.create_all(engine)
