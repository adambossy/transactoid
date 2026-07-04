"""``run_sql`` runs on a read-only role: SELECT is RLS-scoped, DML is rejected.

Postgres-only (roles + RLS), and additionally needs a read-only role URL in
``POSTGRES_TEST_RO_URL`` (a ``penny_agent_ro``-style login granted only
``SELECT``). Skips when either is unset. The read-only role is granted access to
the ``pg_db`` fixture's throwaway schema so the test is self-contained.
"""

import datetime
import os
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import RequestContext

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
UA, UB = uuid.uuid4(), uuid.uuid4()


def _ctx_a() -> RequestContext:
    return RequestContext(user_id=UA, household_id=HA)


def _txn(ext: str, hh, owner):
    return PlaidTransaction(
        external_id=ext,
        source="PLAID",
        account_id="aa",
        item_id="ia",
        posted_at=datetime.date(2026, 1, 1),
        amount_cents=1,
        currency="USD",
        household_id=hh,
        owner_user_id=owner,
        visibility="private",
    )


def _seed(db: DB) -> None:
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
        s.add(_txn("ta", HA, UA))


def _readonly_db(pg_db: DB) -> DB:
    """A DB bound to the read-only role, pointed at pg_db's throwaway schema."""
    ro_url = os.environ.get("POSTGRES_TEST_RO_URL", "").strip()
    if not ro_url:
        pytest.skip("POSTGRES_TEST_RO_URL not set")
    ro_role = os.environ.get("POSTGRES_TEST_RO_ROLE", "penny_agent_ro")
    with pg_db.session() as s:
        schema = s.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The read-only role needs access to this throwaway schema (pg_db owns it).
    with pg_db._engine.begin() as conn:
        conn.execute(sa.text(f'GRANT USAGE ON SCHEMA "{schema}" TO {ro_role}'))
        conn.execute(
            sa.text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO {ro_role}')
        )
    sep = "&" if "?" in ro_url else "?"
    return DB(f"{ro_url}{sep}options=-csearch_path%3D{schema}")


def test_readonly_select_is_rls_scoped(pg_db):
    _seed(pg_db)
    ro = _readonly_db(pg_db)
    with ro.session_for(_ctx_a()) as s:
        n = s.execute(sa.text("SELECT count(*) FROM plaid_transactions")).scalar_one()
    assert n == 1  # RLS still fences the read-only role to household A's row


def test_readonly_insert_is_rejected(pg_db):
    _seed(pg_db)
    ro = _readonly_db(pg_db)
    with pytest.raises(sa.exc.ProgrammingError):  # InsufficientPrivilege
        with ro.session_for(_ctx_a()) as s:
            s.execute(
                sa.text(
                    "INSERT INTO plaid_transactions (external_id, source, "
                    "account_id, item_id, posted_at, amount_cents, currency, "
                    "household_id, owner_user_id, visibility) VALUES "
                    "('evil','PLAID','aa','ia','2026-01-01',1,'USD',:h,:u,'private')"
                ),
                {"h": str(HA), "u": str(UA)},
            )


def test_readonly_delete_is_rejected(pg_db):
    _seed(pg_db)
    ro = _readonly_db(pg_db)
    with pytest.raises(sa.exc.ProgrammingError):  # InsufficientPrivilege
        with ro.session_for(_ctx_a()) as s:
            s.execute(sa.text("DELETE FROM plaid_transactions"))
