import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import PlaidItem, PlaidTransaction
from penny.tenancy.context import (
    NIL_USER_UUID,
    require_request_context,
    reset_request_context,
    set_request_context,
)


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_household_id_required_without_context(tmp_path):
    db = _create_db(tmp_path)
    token = set_request_context(None)
    try:
        with pytest.raises(sa.exc.IntegrityError):
            with db.session() as s:
                s.add(PlaidItem(item_id="i", access_token="t"))
                s.flush()
    finally:
        reset_request_context(token)


def test_context_stamps_tenant_columns_on_insert(tmp_path):
    # The suite-wide autouse RequestContext is stamped onto new rows at flush.
    db = _create_db(tmp_path)
    ctx = require_request_context()
    with db.session() as s:
        s.add(PlaidItem(item_id="i", access_token="t"))
        s.flush()
        item = s.query(PlaidItem).one()
        assert item.household_id == ctx.household_id
        assert item.owner_user_id == ctx.user_id


def test_visibility_value_is_checked(tmp_path):
    db = _create_db(tmp_path)
    with pytest.raises(sa.exc.IntegrityError):
        with db.session() as s:
            s.add(PlaidItem(item_id="i", access_token="t"))
            s.flush()
            s.add(
                PlaidTransaction(
                    external_id="e",
                    source="PLAID",
                    account_id="a",
                    item_id="i",
                    posted_at=datetime.date(2026, 1, 1),
                    amount_cents=1,
                    currency="USD",
                    visibility="bogus",
                )
            )
            s.flush()


def test_owner_cannot_be_the_nil_sentinel(tmp_path):
    # The joint-session sentinel must never own a row: RLS compares
    # owner_user_id to app.current_user, which is the nil UUID in joint mode.
    db = _create_db(tmp_path)
    with pytest.raises(sa.exc.IntegrityError):
        with db.session() as s:
            s.add(PlaidItem(item_id="i", access_token="t", owner_user_id=NIL_USER_UUID))
            s.flush()
