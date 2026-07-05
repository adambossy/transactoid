"""Two self-serve signups are fully isolated (Postgres RLS).

Provisions two independent users via ``resolve_or_provision_identity`` (the same
seam phase-2's auth dependency drives on an unknown user), seeds one Plaid
item/transaction under each user's ``RequestContext``, and asserts that a raw
``SELECT`` — the shape the agent's ``run_sql`` tool rides — from one context sees
none of the other household's rows. This is the open-signup leakage guard.
"""

from __future__ import annotations

import datetime

import pytest
import sqlalchemy as sa

from penny.adapters.db.models import PlaidItem, PlaidTransaction
from penny.signup import resolve_or_provision_identity
from penny.tenancy.context import RequestContext

pytestmark = pytest.mark.postgres


def _seed_txn(s, *, ext, hh, owner):
    s.add(
        PlaidItem(
            item_id=f"item-{ext}",
            access_token="t",
            household_id=hh,
            owner_user_id=owner,
        )
    )
    s.flush()
    s.add(
        PlaidTransaction(
            external_id=ext,
            source="PLAID",
            account_id=f"acct-{ext}",
            item_id=f"item-{ext}",
            posted_at=datetime.date(2026, 1, 1),
            amount_cents=1,
            currency="USD",
            household_id=hh,
            owner_user_id=owner,
            visibility="private",
        )
    )
    s.flush()


def test_two_self_serve_signups_are_isolated(pg_db):
    # Two independent signups → two isolated households (identity tables carry no
    # RLS, so provisioning runs on a plain session, exactly as the auth dep does).
    with pg_db.session() as s:
        ha, ua = resolve_or_provision_identity(
            s, email="a@example.com", external_auth_id="clerk_a"
        )
    with pg_db.session() as s:
        hb, ub = resolve_or_provision_identity(
            s, email="b@example.com", external_auth_id="clerk_b"
        )
    assert ha != hb  # each signup got its own household

    ctx_a = RequestContext(user_id=ua, household_id=ha)
    ctx_b = RequestContext(user_id=ub, household_id=hb)
    with pg_db.session_for(ctx_a) as s:
        _seed_txn(s, ext="a1", hh=ha, owner=ua)
    with pg_db.session_for(ctx_b) as s:
        _seed_txn(s, ext="b1", hh=hb, owner=ub)

    # A raw SELECT (run_sql shape) from A sees only A's row, and vice versa.
    with pg_db.session_for(ctx_a) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
        assert {r[0] for r in rows} == {"a1"}
    with pg_db.session_for(ctx_b) as s:
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
        assert {r[0] for r in rows} == {"b1"}


def test_provisioned_taxonomy_is_per_household(pg_db):
    # Each provisioned household gets its own seeded taxonomy — no shared rows.
    with pg_db.session() as s:
        ha, ua = resolve_or_provision_identity(
            s, email="tax-a@example.com", external_auth_id="clerk_ta"
        )
    with pg_db.session() as s:
        hb, ub = resolve_or_provision_identity(
            s, email="tax-b@example.com", external_auth_id="clerk_tb"
        )
    ctx_a = RequestContext(user_id=ua, household_id=ha)
    with pg_db.session_for(ctx_a) as s:
        counts = s.execute(sa.text("SELECT count(*) FROM categories")).scalar_one()
        household_a_only = s.execute(
            sa.text("SELECT count(*) FROM categories WHERE household_id = :h"),
            {"h": str(hb)},
        ).scalar_one()
    assert counts > 0  # A sees its own taxonomy
    assert household_a_only == 0  # and none of B's, even filtering for it
