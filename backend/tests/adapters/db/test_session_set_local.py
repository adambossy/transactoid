from pathlib import Path
import uuid

import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.tenancy.context import (
    RequestContext,
    SessionMode,
    get_request_context,
    reset_request_context,
    set_request_context,
)


def _db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_session_runs_with_context_on_sqlite_noop(tmp_path):
    # On SQLite, the RLS set_config must be skipped (no error).
    db = _db(tmp_path)
    ctx = RequestContext(
        user_id=uuid.uuid4(), household_id=uuid.uuid4(), session_mode=SessionMode.JOINT
    )
    token = set_request_context(ctx)
    try:
        with db.session() as s:
            s.execute(sa.text("SELECT 1"))
    finally:
        reset_request_context(token)


def test_session_for_sets_and_resets_the_context(tmp_path):
    db = _db(tmp_path)
    outer = get_request_context()
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    with db.session_for(ctx) as s:
        assert get_request_context() is ctx
        s.execute(sa.text("SELECT 1"))
    assert get_request_context() is outer
