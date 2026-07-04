"""End-to-end multi-tenant acceptance battery (Postgres RLS).

The spec's guarantees, asserted through the same seams production uses:
cross-household isolation (even via the facade's raw-SQL path the agent's
run_sql tool rides), within-household privacy, shared visibility, joint
sessions, and the WITH CHECK write fence.
"""

import datetime
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import (
    RequestContext,
    SessionMode,
    reset_request_context,
    set_request_context,
)

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
U1, U2 = uuid.uuid4(), uuid.uuid4()  # spouses in household A
UB = uuid.uuid4()  # household B's user

CTX_U1 = RequestContext(user_id=U1, household_id=HA)
CTX_U2 = RequestContext(user_id=U2, household_id=HA)
CTX_JOINT = RequestContext(user_id=U1, household_id=HA, session_mode=SessionMode.JOINT)
CTX_B = RequestContext(user_id=UB, household_id=HB)


def _txn(ext: str, item: str, hh, owner, vis):
    return PlaidTransaction(
        external_id=ext,
        source="PLAID",
        account_id=f"acct-{ext}",
        item_id=item,
        posted_at=datetime.date(2026, 1, 1),
        amount_cents=1,
        currency="USD",
        household_id=hh,
        owner_user_id=owner,
        visibility=vis,
    )


def _seed(db):
    with db.session() as s:  # identity tables carry no RLS
        s.add_all(
            [Household(household_id=HA, name="A"), Household(household_id=HB, name="B")]
        )
        s.flush()
        s.add_all(
            [
                User(user_id=U1, household_id=HA, email=f"{U1}@x.com"),
                User(user_id=U2, household_id=HA, email=f"{U2}@x.com"),
                User(user_id=UB, household_id=HB, email=f"{UB}@x.com"),
            ]
        )
    # Financial rows must be written under their owner's context (FORCE RLS).
    with db.session_for(CTX_U1) as s:
        s.add(
            PlaidItem(item_id="ia", access_token="t", household_id=HA, owner_user_id=U1)
        )
        s.flush()
        s.add(_txn("p1", "ia", HA, U1, "private"))
        s.add(_txn("sh", "ia", HA, U1, "shared"))
    with db.session_for(CTX_U2) as s:
        s.add(_txn("p2", "ia", HA, U2, "private"))
    with db.session_for(CTX_B) as s:
        s.add(
            PlaidItem(item_id="ib", access_token="t", household_id=HB, owner_user_id=UB)
        )
        s.flush()
        s.add(_txn("fb", "ib", HB, UB, "private"))


def _visible_exts(db, ctx) -> set[str]:
    with db.session_for(ctx) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    return {r[0] for r in rows}


def test_run_sql_select_star_returns_only_own_household(pg_db):
    _seed(pg_db)
    # The facade's run_sql (the agent tool's engine) opens its own session,
    # which reads the ambient context — exactly how a chat request runs.
    token = set_request_context(CTX_U1)
    try:
        rows = pg_db.run_sql(
            "SELECT * FROM plaid_transactions",
            model=PlaidTransaction,
            pk_column="plaid_transaction_id",
        )
    finally:
        reset_request_context(token)
    assert {r.external_id for r in rows} == {"p1", "sh"}


def test_within_household_private_account_hidden_from_spouse(pg_db):
    _seed(pg_db)
    assert "p2" not in _visible_exts(pg_db, CTX_U1)
    assert "p1" not in _visible_exts(pg_db, CTX_U2)


def test_shared_account_visible_to_both_spouses(pg_db):
    _seed(pg_db)
    assert "sh" in _visible_exts(pg_db, CTX_U1)
    assert "sh" in _visible_exts(pg_db, CTX_U2)


def test_joint_session_sees_shared_only(pg_db):
    _seed(pg_db)
    assert _visible_exts(pg_db, CTX_JOINT) == {"sh"}


def test_write_cannot_set_foreign_household_id(pg_db):
    _seed(pg_db)
    with pytest.raises(sa.exc.DBAPIError):  # RLS WITH CHECK rejects it
        with pg_db.session_for(CTX_U1) as s:
            s.add(_txn("evil", "ia", HB, UB, "private"))
            s.flush()
