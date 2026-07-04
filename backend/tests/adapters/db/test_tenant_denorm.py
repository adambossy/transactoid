"""Tenant columns on account-linked rows denormalize from plaid_accounts.

The account row is the source of truth for (household, owner, visibility);
stamping those from the requesting session instead (e.g. 'shared' because the
session is joint) would leak a private account's transactions to the whole
household.
"""

import datetime
import uuid

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    Household,
    PlaidAccount,
    PlaidItem,
    PlaidTransaction,
    User,
)
from penny.tenancy.context import RequestContext, SessionMode

H = uuid.uuid4()
U1 = uuid.uuid4()
U2 = uuid.uuid4()

JOINT = RequestContext(user_id=U2, household_id=H, session_mode=SessionMode.JOINT)


def _seed(tmp_path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add(Household(household_id=H, name="Bossy"))
        s.flush()
        s.add_all(
            [
                User(user_id=U1, household_id=H, email="a@x.com"),
                User(user_id=U2, household_id=H, email="b@x.com"),
                PlaidItem(
                    item_id="i1", access_token="t", household_id=H, owner_user_id=U1
                ),
            ]
        )
        s.flush()
        s.add(
            PlaidAccount(
                account_id="acct-priv",
                item_id="i1",
                owner_user_id=U1,
                household_id=H,
                visibility="private",
            )
        )
    return db


def _txn_dict(ext: str, acct: str) -> dict:
    return {
        "external_id": ext,
        "source": "PLAID",
        "account_id": acct,
        "item_id": "i1",
        "posted_at": datetime.date(2026, 1, 1),
        "amount_cents": 1,
        "currency": "USD",
    }


def test_bulk_upsert_in_joint_session_keeps_private_account_private(tmp_path):
    db = _seed(tmp_path)
    with db.session_for(JOINT):
        db.bulk_upsert_plaid_transactions([_txn_dict("e1", "acct-priv")])
    with db.session() as s:
        txn = s.query(PlaidTransaction).filter_by(external_id="e1").one()
        assert txn.visibility == "private"
        assert txn.owner_user_id == U1
        assert txn.household_id == H


def test_orm_insert_denormalizes_from_account(tmp_path):
    db = _seed(tmp_path)
    with db.session_for(JOINT) as s:
        s.add(
            PlaidTransaction(
                external_id="e2",
                source="PLAID",
                account_id="acct-priv",
                item_id="i1",
                posted_at=datetime.date(2026, 1, 1),
                amount_cents=1,
                currency="USD",
            )
        )
        s.flush()
        txn = s.query(PlaidTransaction).filter_by(external_id="e2").one()
        assert txn.visibility == "private"
        assert txn.owner_user_id == U1


def test_derived_transaction_mirrors_its_plaid_row(tmp_path):
    db = _seed(tmp_path)
    with db.session_for(RequestContext(user_id=U1, household_id=H)):
        db.bulk_upsert_plaid_transactions([_txn_dict("e3", "acct-priv")])
    with db.session() as s:
        plaid_id = (
            s.query(PlaidTransaction).filter_by(external_id="e3").one()
        ).plaid_transaction_id
    with db.session_for(JOINT):
        derived = db.insert_derived_transaction(
            {
                "plaid_transaction_id": plaid_id,
                "external_id": "e3",
                "amount_cents": 1,
                "posted_at": datetime.date(2026, 1, 1),
            }
        )
    assert derived.visibility == "private"
    assert derived.owner_user_id == U1


def test_rows_without_account_row_fall_back_to_context(tmp_path):
    db = _seed(tmp_path)
    with db.session_for(RequestContext(user_id=U2, household_id=H)):
        db.bulk_upsert_plaid_transactions([_txn_dict("e4", "acct-unknown")])
    with db.session() as s:
        txn = s.query(PlaidTransaction).filter_by(external_id="e4").one()
        assert txn.visibility == "private"
        assert txn.owner_user_id == U2
