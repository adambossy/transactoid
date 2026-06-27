from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import penny.api.main
from penny.api.persistence.engine import reset_web_engine
import penny.db
import penny.services


@pytest.fixture(autouse=True, scope="session")
def _disable_observability() -> None:
    """Hard-disable Langfuse/OTEL tracing for the whole test session.

    Tests run with a developer's real Langfuse keys in scope (``load_dotenv``
    walks up and finds the parent worktree's ``.env``), so without this the
    fixture agent runs in tests/api/ export ``penny-agent-run`` traces to the
    live cloud project. Null the cached globals before anything can resolve
    ``is_enabled()`` to True. ``test_otel.py`` re-enables tracing per-test via
    its own ``monkeypatch``-based fixtures, which restore these afterward.
    """
    from penny.observability import otel as ot

    ot._enabled = False
    ot._provider = None


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
