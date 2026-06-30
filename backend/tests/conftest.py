from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import penny.api.main
from penny.api.persistence.engine import reset_web_engine
import penny.db
import penny.observability.otel as _otel
import penny.services


@pytest.fixture(autouse=True)
def _no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard-disable Langfuse/OTEL tracing for every test.

    Tracing turns on automatically whenever ``LANGFUSE_PUBLIC_KEY`` +
    ``LANGFUSE_SECRET_KEY`` are present (e.g. exported into the shell, or
    sourced from ``.env.test``), so a bare ``pytest`` run would otherwise ship
    synthetic spans to the real Langfuse project. Force the explicit-off flag
    and pin the cached enablement decision so no test — fixture or scripted
    fake agent — can emit a trace.
    """
    monkeypatch.setenv("PENNY_LANGFUSE_ENABLED", "false")
    monkeypatch.setattr(_otel, "_enabled", False)
    monkeypatch.setattr(_otel, "_provider", None)


def _reset_singletons() -> None:
    penny.db._db = None
    penny.services._taxonomy = None
    penny.services._rules_loader = None
    penny.services._persister = None
    penny.services._migrator = None
    penny.api.main._conversation_store = None
    reset_web_engine()


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the process-wide finance + website DBs at fresh tmp SQLite files."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PENNY_WEB_DATABASE_URL", f"sqlite:///{tmp_path / 'web.db'}")
    _reset_singletons()
    yield
    _reset_singletons()


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the workspace at a tmp dir so tests never touch ~/.transactoid."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("PENNY_WORKSPACE", str(workspace))
    return workspace
