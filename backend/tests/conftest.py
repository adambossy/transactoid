from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import uuid

import pytest

# Run the suite in dev auth mode with an env-pinned principal that matches the
# autouse RequestContext below, so importing the FastAPI app (which validates
# auth config at import) does not fail closed, and the auth dependency resolves
# to the same principal the tests already run as. Clerk-mode tests override the
# settings/verifier explicitly (see tests/api/test_auth_dependency.py).
os.environ.setdefault("PENNY_AUTH_MODE", "dev")
os.environ.setdefault("PENNY_DEV_USER_ID", "11111111-1111-1111-1111-111111111111")
os.environ.setdefault("PENNY_DEV_HOUSEHOLD_ID", "22222222-2222-2222-2222-222222222222")
# Sentry defaults on (project DSN is baked in); disable it for the suite so
# importing the app never initializes error reporting and test-triggered
# exceptions can't leak to the prod Sentry project. Set before importing
# penny.api.main below, which calls init_sentry() at import.
os.environ.setdefault("PENNY_SENTRY_ENABLED", "false")

import penny.api.auth as _api_auth
import penny.api.main
from penny.api.persistence.engine import reset_web_engine
import penny.db
import penny.observability.otel as _otel
import penny.services
from penny.tenancy.context import (
    RequestContext,
    reset_request_context,
    set_request_context,
)

# Re-exported so the @pytest.mark.postgres suites find it; pytest only
# auto-imports files named exactly conftest.py.
from tests.conftest_postgres import pg_db  # noqa: F401

# The well-known principal every test runs as (mirroring production, where
# every request carries a RequestContext — see the autouse fixture below).
# FK-enforcing DB tests materialize these rows with seed_test_identity().
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TEST_HOUSEHOLD_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _request_context() -> Iterator[RequestContext]:
    """Run every test under a dev RequestContext.

    Tenant columns are NOT NULL and stamped at flush from the current context,
    so DB writes need a principal exactly as production requests do. Tests
    exercising the no-context path set ``set_request_context(None)`` locally.
    """
    ctx = RequestContext(user_id=TEST_USER_ID, household_id=TEST_HOUSEHOLD_ID)
    token = set_request_context(ctx)
    yield ctx
    reset_request_context(token)


def seed_test_identity(db) -> None:  # noqa: ANN001 - avoids a facade import cycle here
    """Insert the household/user rows the autouse RequestContext points at.

    Needed wherever SQLite FKs are enforced: stamped tenant columns reference
    households/users, which must then actually exist. Idempotent.
    """
    from penny.adapters.db.models import Household, User

    with db.session() as s:
        if s.get(Household, TEST_HOUSEHOLD_ID) is None:
            s.add(Household(household_id=TEST_HOUSEHOLD_ID, name="Test Household"))
            s.flush()
        if s.get(User, TEST_USER_ID) is None:
            s.add(
                User(
                    user_id=TEST_USER_ID,
                    household_id=TEST_HOUSEHOLD_ID,
                    email="test@example.com",
                )
            )


@pytest.fixture(autouse=True)
def _seed_identity_with_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every schema a test creates also gets the test identity rows.

    Mirrors production, where bootstrap guarantees the requesting principal
    exists before any financial write.
    """
    from penny.adapters.db.facade import DB

    original = DB.create_schema

    def create_schema_and_seed(self: DB) -> None:
        original(self)
        seed_test_identity(self)

    monkeypatch.setattr(DB, "create_schema", create_schema_and_seed)


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
    penny.db._readonly_db = None
    penny.services._taxonomy = None
    penny.services._rules_loader = None
    penny.services._persister = None
    penny.services._migrator = None
    penny.api.main._conversation_store = None
    # Auth settings/verifier are lru_cached; drop them so a test that repoints
    # the DB or env sees a fresh resolution. Guard cache_clear because a test
    # may have monkeypatched these with a plain callable.
    for fn in (_api_auth.get_auth_settings, _api_auth.get_verifier):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
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
