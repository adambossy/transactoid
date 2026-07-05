import datetime
import uuid

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import RequestContext, SessionMode

H = uuid.uuid4()
U1 = uuid.uuid4()
U2 = uuid.uuid4()


def _seed(tmp_path):
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
        # one private (U2) and one shared (U1) transaction
        for ext, owner, vis in [("priv", U2, "private"), ("shar", U1, "shared")]:
            s.add(
                PlaidTransaction(
                    external_id=ext,
                    source="PLAID",
                    account_id="acct",
                    item_id="i1",
                    posted_at=datetime.date(2026, 1, 1),
                    amount_cents=1,
                    currency="USD",
                    household_id=H,
                    owner_user_id=owner,
                    visibility=vis,
                )
            )
    return db


def test_individual_sees_own_private_plus_shared(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H)
    with db.session_for(ctx) as s:
        rows = db.list_visible_plaid_transactions(s)
        exts = {r.external_id for r in rows}
    assert exts == {"shar"}  # U1 sees shared; U2's private is hidden


def test_owner_sees_their_own_private(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U2, household_id=H)
    with db.session_for(ctx) as s:
        exts = {r.external_id for r in db.list_visible_plaid_transactions(s)}
    assert exts == {"priv", "shar"}


def test_joint_sees_shared_only(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H, session_mode=SessionMode.JOINT)
    with db.session_for(ctx) as s:
        exts = {r.external_id for r in db.list_visible_plaid_transactions(s)}
    assert exts == {"shar"}


def test_other_household_sees_nothing(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    with db.session_for(ctx) as s:
        assert db.list_visible_plaid_transactions(s) == []


def test_date_range_lister_applies_visibility(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H)
    with db.session_for(ctx):
        rows = db.list_plaid_transactions_in_date_range(
            start=datetime.date(2025, 12, 31), end=datetime.date(2026, 1, 2)
        )
    assert {r.external_id for r in rows} == {"shar"}
