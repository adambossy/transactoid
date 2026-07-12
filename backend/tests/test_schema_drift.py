"""Drift guard: the models (``create_all``) and the migration chain
(``alembic upgrade head``) must describe the same schema.

- Finance ``Base`` runs on SQLite — the chain is SQLite-clean, and the
  Postgres-only constructs (RLS, GUC) are guarded out of *both* sides there, so
  a table+column comparison is apples-to-apples. Catches "changed a model,
  forgot the migration" (and vice versa).
- ``WebBase`` runs on Postgres: the web migrations are Postgres-guarded, so
  SQLite never exercises them. This is the case the review flagged — a fresh,
  alembic-only Postgres DB must build the whole ``web`` schema (migration 019
  creates the conversation tables, not just ALTERs them) and match the models.

See docs/superpowers/plans/2026-07-09-alembic-sole-authority-on-postgres.md.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

from penny.adapters.db.models import Base
from penny.api.persistence.models import WebBase
from penny.schema import upgrade_to_head


def _schema(engine: Engine) -> dict[str, list[str]]:
    insp = inspect(engine)
    return {
        t: sorted(c["name"] for c in insp.get_columns(t))
        for t in insp.get_table_names()
    }


def test_finance_models_match_migrations(tmp_path):
    # The explicit URL wins over any ambient DATABASE_URL (env.py precedence).
    mig_url = f"sqlite:///{tmp_path / 'mig.db'}"
    upgrade_to_head(mig_url)
    migrated = _schema(create_engine(mig_url))
    migrated.pop("alembic_version", None)

    mdl_engine = create_engine(f"sqlite:///{tmp_path / 'mdl.db'}")
    Base.metadata.create_all(mdl_engine)
    models = _schema(mdl_engine)

    assert models == migrated, (
        "finance models drifted from the migration chain — a model change needs "
        "a migration (or vice versa).\n"
        f"  tables only in models:     {sorted(set(models) - set(migrated))}\n"
        f"  tables only in migrations: {sorted(set(migrated) - set(models))}\n"
        f"  column diffs: "
        + str(
            {
                t: {"models": models[t], "migrations": migrated[t]}
                for t in set(models) & set(migrated)
                if models[t] != migrated[t]
            }
        )
    )


@pytest.mark.postgres
def test_fresh_postgres_builds_web_schema_matching_models():
    """A fresh Postgres ``upgrade_to_head`` must build the entire ``web`` schema
    (not just ALTER pre-existing tables) and match the WebBase models.

    Needs a superuser URL to CREATE/DROP a throwaway database: the chain
    hardcodes the ``web``/public schemas, so a per-test schema can't isolate it.
    Skips when unset, like the RLS suites without POSTGRES_TEST_URL.
    """
    su_url = os.environ.get("POSTGRES_SUPERUSER_URL", "").strip()
    if not su_url:
        pytest.skip("POSTGRES_SUPERUSER_URL not set")

    dbname = f"migtest_{uuid.uuid4().hex[:8]}"
    admin = create_engine(su_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    target_url = su_url.rsplit("/", 1)[0] + "/" + dbname
    try:
        upgrade_to_head(target_url)
        target_engine = create_engine(target_url)
        insp = inspect(target_engine)

        web_tables = set(insp.get_table_names(schema="web"))
        assert {"conversations", "conversation_messages"} <= web_tables, (
            "fresh Postgres migration did not build the web conversation tables; "
            f"web schema has: {sorted(web_tables)}"
        )
        # Every WebBase table must be built by the chain and match the model.
        for qualified, table in WebBase.metadata.tables.items():
            name = qualified.split(".")[-1]
            migrated_cols = {c["name"] for c in insp.get_columns(name, schema="web")}
            model_cols = {c.name for c in table.columns}
            assert migrated_cols == model_cols, (
                f"web.{name} drifted from the model — only in model: "
                f"{model_cols - migrated_cols}; only in migrations: "
                f"{migrated_cols - model_cols}"
            )
        target_engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()
