"""The run_sql GUC-override RLS bypass is closed (findings F02/F05).

An authenticated attacker who knows a victim's household UUID could craft a
single-statement query that flips ``app.current_household`` before RLS evaluates
the scan::

    WITH c AS (SELECT set_config('app.current_household', '<victim>', true))
    SELECT * FROM plaid_transactions, c

The fix revokes EXECUTE on ``set_config`` from the read-only agent role (from
PUBLIC, re-granted to the owner) and pins the tenant through the *set-once*
``penny_set_tenant`` SECURITY DEFINER wrapper. This test proves, against a real
non-superuser Postgres role, that neither the direct-``set_config`` nor the
wrapper-re-call override can leak another household's rows.

Postgres-only (roles + RLS + SECURITY DEFINER). Needs ``POSTGRES_TEST_URL`` (via
the ``pg_db`` fixture) and a read-only role URL in ``POSTGRES_TEST_RO_URL``;
skips cleanly otherwise.
"""

import datetime
import os
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.adapters.db.rls import revoke_guc_override
from penny.tenancy.context import RequestContext

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
UA, UB = uuid.uuid4(), uuid.uuid4()


def _ctx_a() -> RequestContext:
    return RequestContext(user_id=UA, household_id=HA)


def _txn(ext: str, hh: uuid.UUID, owner: uuid.UUID) -> PlaidTransaction:
    return PlaidTransaction(
        external_id=ext,
        source="PLAID",
        account_id="aa",
        item_id=f"i-{hh}",
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
    # One private transaction per household so a successful bypass would surface
    # B's row to A. Seed each under its own context (RLS WITH CHECK on insert).
    with db.session_for(_ctx_a()) as s:
        s.add(
            PlaidItem(
                item_id=f"i-{HA}", access_token="t", household_id=HA, owner_user_id=UA
            )
        )
        s.flush()
        s.add(_txn("ta", HA, UA))
    with db.session_for(RequestContext(user_id=UB, household_id=HB)) as s:
        s.add(
            PlaidItem(
                item_id=f"i-{HB}", access_token="t", household_id=HB, owner_user_id=UB
            )
        )
        s.flush()
        s.add(_txn("tb", HB, UB))


@pytest.fixture
def hardened_ro(pg_db: DB):
    """A read-only DB bound to the agent role, hardened against the GUC override.

    Grants the throwaway schema to the read-only role, revokes set_config
    (re-granting to the owner), and grants the penny_set_tenant wrapper — exactly
    the prod .env.example DDL. The PUBLIC set_config grant is restored on teardown
    so other Postgres-marked tests are unaffected.
    """
    ro_url = os.environ.get("POSTGRES_TEST_RO_URL", "").strip()
    if not ro_url:
        pytest.skip("POSTGRES_TEST_RO_URL not set")
    ro_role = os.environ.get("POSTGRES_TEST_RO_ROLE", "penny_agent_ro")
    with pg_db.session() as s:
        schema = s.execute(sa.text("SELECT current_schema()")).scalar_one()
        owner = s.execute(sa.text("SELECT current_user")).scalar_one()
    with pg_db._engine.begin() as conn:
        conn.execute(sa.text(f'GRANT USAGE ON SCHEMA "{schema}" TO {ro_role}'))
        conn.execute(
            sa.text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO {ro_role}')
        )
        revoke_guc_override(conn, agent_role=ro_role, owner_role=owner)
    sep = "&" if "?" in ro_url else "?"
    ro = DB(
        f"{ro_url}{sep}options=-csearch_path%3D{schema}", use_tenant_guc_wrapper=True
    )
    try:
        yield ro
    finally:
        ro._engine.dispose()
        with pg_db._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "GRANT EXECUTE ON FUNCTION "
                    "pg_catalog.set_config(text, text, boolean) TO PUBLIC"
                )
            )


def test_legitimate_scoped_read_still_works(pg_db, hardened_ro):
    # The wrapper must still pin the agent's own context: A sees only A's row.
    _seed(pg_db)
    with hardened_ro.session_for(_ctx_a()) as s:
        n = s.execute(sa.text("SELECT count(*) FROM plaid_transactions")).scalar_one()
    assert n == 1


def test_direct_set_config_override_is_denied(pg_db, hardened_ro):
    _seed(pg_db)
    # EXECUTE on set_config is revoked from the agent role -> permission denied,
    # so the CTE cannot flip the household to B before the scan.
    with pytest.raises(sa.exc.ProgrammingError):
        with hardened_ro.session_for(_ctx_a()) as s:
            s.execute(
                sa.text(
                    "WITH c AS (SELECT set_config('app.current_household', :hb, true)) "
                    "SELECT count(*) FROM plaid_transactions, c"
                ),
                {"hb": str(HB)},
            )


def test_wrapper_recall_override_is_rejected(pg_db, hardened_ro):
    _seed(pg_db)
    # Even the wrapper cannot be re-invoked to flip the household: it is set-once,
    # already pinned to A at session open, so a re-call raises.
    with pytest.raises(sa.exc.DatabaseError):
        with hardened_ro.session_for(_ctx_a()) as s:
            s.execute(
                sa.text(
                    "WITH c AS (SELECT penny_set_tenant(:hb, :hb)) "
                    "SELECT count(*) FROM plaid_transactions, c"
                ),
                {"hb": str(HB)},
            )
