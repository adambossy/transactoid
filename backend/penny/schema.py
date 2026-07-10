"""Schema authority.

Alembic owns durable (Postgres) schemas; ``create_all`` owns ephemeral SQLite
(local dev, the test suite, the eval store). This module is the single
in-process entry point for applying migrations — used by the ``penny migrate``
CLI (the prod release step) and the schema-drift test.

See ``docs/superpowers/plans/2026-07-09-alembic-sole-authority-on-postgres.md``
for the why: running ``create_all`` on a Postgres DB makes it a second, silent
schema authority that collides with alembic (the phase-3 cutover root cause).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

# alembic.ini lives at backend/; %(here)s resolves there, so version_locations
# (%(here)s/db/migrations) finds the version scripts regardless of caller cwd.
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def upgrade_to_head(database_url: str | None = None) -> None:
    """Apply alembic migrations to head. Idempotent (no-op when already at head).

    ``env.py`` honors ``DATABASE_URL``; ``database_url`` sets the config url
    explicitly (used by tests and the CLI when the env var is not the target).
    """
    cfg = Config(str(_ALEMBIC_INI))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
