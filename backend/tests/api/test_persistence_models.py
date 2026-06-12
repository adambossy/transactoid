"""The conversation tables build on their own Base and are kept off finance."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from penny.adapters.db.models import Base as FinanceBase
from penny.api.persistence.models import WebBase


def test_finance_metadata_excludes_conversation_tables():
    # input: the finance declarative base's table registry
    finance_tables = set(FinanceBase.metadata.tables)

    # act/expected: conversation tables are NOT registered on the finance Base
    # (so the agent's run_sql engine never sees them).
    assert not any(
        name.endswith("conversations") or name.endswith("conversation_messages")
        for name in finance_tables
    )


def test_web_metadata_includes_conversation_tables():
    # input: the website base's table registry
    web_tables = set(WebBase.metadata.tables)

    # expected: both conversation tables live on the website Base
    assert {"web.conversations", "web.conversation_messages"} == web_tables


def test_create_web_schema_builds_tables_on_sqlite(tmp_path: Path):
    # input: a fresh SQLite engine with the web schema translated to None
    engine = create_engine(f"sqlite:///{tmp_path / 'web.db'}")
    engine = engine.execution_options(schema_translate_map={"web": None})

    # act: create the tables
    WebBase.metadata.create_all(engine)

    # expected: both tables exist
    table_names = set(inspect(engine).get_table_names())
    assert {"conversations", "conversation_messages"} <= table_names


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
