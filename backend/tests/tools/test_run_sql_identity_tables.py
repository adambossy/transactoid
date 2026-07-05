"""run_sql cannot read the RLS-exempt identity tables (finding F04).

users/households carry no RLS policy, so a blanket ``GRANT SELECT ON ALL TABLES``
let the agent's read-only run_sql ``SELECT email, external_auth_id FROM users``
and enumerate every user + household across all tenants. The fix revokes SELECT
on those two tables from the agent role. This test proves the revoke denies the
identity reads while leaving finance reads intact.

Postgres-only (roles + RLS). Needs ``POSTGRES_TEST_URL`` (via ``pg_db``) and a
read-only role URL in ``POSTGRES_TEST_RO_URL``; skips cleanly otherwise.
"""

import datetime
import os
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.adapters.db.rls import revoke_identity_table_reads
from penny.tenancy.context import RequestContext

pytestmark = pytest.mark.postgres

HA = uuid.uuid4()
UA = uuid.uuid4()


def _ctx_a() -> RequestContext:
    return RequestContext(user_id=UA, household_id=HA)


def _seed(db: DB) -> None:
    with db.session() as s:  # identity tables carry no RLS
        s.add(Household(household_id=HA, name="A"))
        s.flush()
        s.add(User(user_id=UA, household_id=HA, email=f"{UA}@x.com"))
    with db.session_for(_ctx_a()) as s:
        s.add(
            PlaidItem(item_id="ia", access_token="t", household_id=HA, owner_user_id=UA)
        )
        s.flush()
        s.add(
            PlaidTransaction(
                external_id="ta",
                source="PLAID",
                account_id="aa",
                item_id="ia",
                posted_at=datetime.date(2026, 1, 1),
                amount_cents=1,
                currency="USD",
                household_id=HA,
                owner_user_id=UA,
                visibility="private",
            )
        )


@pytest.fixture
def ro(pg_db: DB) -> DB:
    """Read-only role granted the schema, then hardened per F04 (identity revoke)."""
    ro_url = os.environ.get("POSTGRES_TEST_RO_URL", "").strip()
    if not ro_url:
        pytest.skip("POSTGRES_TEST_RO_URL not set")
    ro_role = os.environ.get("POSTGRES_TEST_RO_ROLE", "penny_agent_ro")
    with pg_db.session() as s:
        schema = s.execute(sa.text("SELECT current_schema()")).scalar_one()
    with pg_db._engine.begin() as conn:
        conn.execute(sa.text(f'GRANT USAGE ON SCHEMA "{schema}" TO {ro_role}'))
        conn.execute(
            sa.text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO {ro_role}')
        )
        revoke_identity_table_reads(conn, agent_role=ro_role)
    sep = "&" if "?" in ro_url else "?"
    return DB(f"{ro_url}{sep}options=-csearch_path%3D{schema}")


@pytest.mark.parametrize("table", ["users", "households"])
def test_identity_table_select_is_denied(pg_db, ro, table):
    _seed(pg_db)
    with pytest.raises(sa.exc.ProgrammingError):  # InsufficientPrivilege
        with ro.session_for(_ctx_a()) as s:
            s.execute(sa.text(f"SELECT * FROM {table}"))  # noqa: S608 - fixed param


def test_finance_read_still_works(pg_db, ro):
    # The revoke is surgical: finance tables remain readable (RLS-scoped).
    _seed(pg_db)
    with ro.session_for(_ctx_a()) as s:
        n = s.execute(sa.text("SELECT count(*) FROM plaid_transactions")).scalar_one()
    assert n == 1
