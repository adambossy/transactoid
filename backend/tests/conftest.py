from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import penny.db
import penny.services


def _reset_singletons() -> None:
    penny.db._db = None
    penny.services._taxonomy = None
    penny.services._rules_loader = None
    penny.services._persister = None
    penny.services._migrator = None
    from penny.api.persistence.engine import reset_web_engine

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
