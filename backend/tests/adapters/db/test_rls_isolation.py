"""Postgres RLS isolation — runs only when POSTGRES_TEST_URL is set.

FORCE ROW LEVEL SECURITY applies even to the table owner, so seeding financial
rows must happen under each household's own RequestContext (identity tables —
households/users — carry no RLS and seed context-free).
"""

import datetime
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import RequestContext, SessionMode

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
UA, UB = uuid.uuid4(), uuid.uuid4()


def _ctx_a() -> RequestContext:
    return RequestContext(user_id=UA, household_id=HA)


def _ctx_b() -> RequestContext:
    return RequestContext(user_id=UB, household_id=HB)


def _txn(ext: str, acct: str, item: str, hh, owner, vis="private"):
    return PlaidTransaction(
        external_id=ext,
        source="PLAID",
        account_id=acct,
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
                User(user_id=UA, household_id=HA, email=f"{UA}@x.com"),
                User(user_id=UB, household_id=HB, email=f"{UB}@x.com"),
            ]
        )
    with db.session_for(_ctx_a()) as s:
        s.add(
            PlaidItem(item_id="ia", access_token="t", household_id=HA, owner_user_id=UA)
        )
        s.flush()
        s.add(_txn("ta", "aa", "ia", HA, UA))
    with db.session_for(_ctx_b()) as s:
        s.add(
            PlaidItem(item_id="ib", access_token="t", household_id=HB, owner_user_id=UB)
        )
        s.flush()
        s.add(_txn("tb", "ab", "ib", HB, UB))


def test_household_a_cannot_see_household_b_even_via_raw_sql(pg_db):
    _seed(pg_db)
    with pg_db.session_for(_ctx_a()) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert {r[0] for r in rows} == {"ta"}


def test_household_b_sees_only_its_own(pg_db):
    _seed(pg_db)
    with pg_db.session_for(_ctx_b()) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert {r[0] for r in rows} == {"tb"}


def test_joint_session_hides_private_rows(pg_db):
    _seed(pg_db)
    joint = RequestContext(user_id=UA, household_id=HA, session_mode=SessionMode.JOINT)
    with pg_db.session_for(joint) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert rows == []  # ta is private; joint sessions see shared only


def test_write_into_foreign_household_is_rejected(pg_db):
    _seed(pg_db)
    with pytest.raises(sa.exc.DBAPIError):  # WITH CHECK violation
        with pg_db.session_for(_ctx_a()) as s:
            s.add(_txn("evil", "aa", "ia", HB, UB))
            s.flush()


def test_write_of_shared_row_for_another_member_is_allowed(pg_db):
    # The WITH CHECK fence is the household, and Postgres additionally
    # requires INSERT..RETURNING rows to be readable by the writer. Net
    # semantics: a member may create rows owned by another member as long as
    # they're shared (e.g. syncing a spouse's shared account)...
    _seed(pg_db)
    other = uuid.uuid4()
    with pg_db.session() as s:  # identity tables carry no RLS
        s.add(User(user_id=other, household_id=HA, email=f"{other}@x.com"))
    with pg_db.session_for(_ctx_a()) as s:
        s.add(_txn("spouse-shared", "aa", "ia", HA, other, "shared"))
        s.flush()
    with pg_db.session_for(_ctx_a()) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert "spouse-shared" in {r[0] for r in rows}


def test_write_of_private_row_for_another_member_is_rejected(pg_db):
    # ...but NOT rows they could not read back: another member's private row
    # fails loudly rather than materializing data invisible to its writer.
    _seed(pg_db)
    other = uuid.uuid4()
    with pg_db.session() as s:
        s.add(User(user_id=other, household_id=HA, email=f"{other}@x.com"))
    with pytest.raises(sa.exc.DBAPIError):
        with pg_db.session_for(_ctx_a()) as s:
            s.add(_txn("spouse-private", "aa", "ia", HA, other, "private"))
            s.flush()


def test_contextless_session_on_pooled_connection_returns_empty(pg_db):
    # set_config(..., true) reverts the GUC to '' (not unset) when the
    # transaction ends; the policy must treat '' as NULL so a later
    # context-less session on the same pooled connection reads nothing
    # instead of erroring on ''::uuid.
    from penny.tenancy.context import reset_request_context, set_request_context

    _seed(pg_db)
    with pg_db.session_for(_ctx_a()) as s:
        s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    token = set_request_context(None)
    try:
        with pg_db.session() as s:
            rows = s.execute(
                sa.text("SELECT external_id FROM plaid_transactions")
            ).all()
        assert rows == []
    finally:
        reset_request_context(token)


def test_gucs_survive_commit_within_a_session(pg_db):
    # The GUCs are transaction-local; a commit mid-session starts a new
    # transaction which must be re-stamped, or post-commit reads (e.g.
    # session.refresh after commit) see nothing.
    _seed(pg_db)
    with pg_db.session_for(_ctx_a()) as s:
        s.add(_txn("post-commit", "aa", "ia", HA, UA, "private"))
        s.commit()
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert "post-commit" in {r[0] for r in rows}
