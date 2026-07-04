import datetime
from pathlib import Path
import uuid

import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import PlaidItem, PlaidTransaction, Tag
from penny.db_backfill import backfill_household

H = uuid.UUID("22222222-2222-2222-2222-222222222222")
U1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
U2 = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _seed(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add(PlaidItem(item_id="item-1", access_token="tok"))
        s.flush()
        s.add(
            PlaidTransaction(
                external_id="e1",
                source="PLAID",
                account_id="acct-1",
                item_id="item-1",
                posted_at=datetime.date(2026, 1, 1),
                amount_cents=100,
                currency="USD",
            )
        )
        s.add(Tag(name="vacation"))
    return db


def test_backfill_assigns_household_and_creates_accounts(tmp_path):
    db = _seed(tmp_path)
    with db.session() as s:
        backfill_household(
            s,
            household_id=H,
            name="Bossy",
            user1=(U1, "adam@example.com"),
            user2=(U2, "wife@example.com"),
        )
    with db.session() as s:
        txn = s.query(PlaidTransaction).filter_by(external_id="e1").one()
        assert txn.household_id == H
        assert txn.owner_user_id == U1
        assert txn.visibility == "private"
        item = s.query(PlaidItem).filter_by(item_id="item-1").one()
        assert item.household_id == H
        assert item.owner_user_id == U1
        tag = s.query(Tag).filter_by(name="vacation").one()
        assert tag.household_id == H
        accts = s.execute(
            sa.text("SELECT account_id, item_id, visibility FROM plaid_accounts")
        ).all()
        assert [tuple(a) for a in accts] == [("acct-1", "item-1", "private")]


def test_backfill_is_idempotent(tmp_path):
    db = _seed(tmp_path)
    for _ in range(2):
        with db.session() as s:
            backfill_household(
                s,
                household_id=H,
                name="Bossy",
                user1=(U1, "adam@example.com"),
                user2=(U2, "wife@example.com"),
            )
    with db.session() as s:
        assert s.execute(sa.text("SELECT COUNT(*) FROM households")).scalar() == 1
        assert s.execute(sa.text("SELECT COUNT(*) FROM users")).scalar() == 2
        assert s.execute(sa.text("SELECT COUNT(*) FROM plaid_accounts")).scalar() == 1
