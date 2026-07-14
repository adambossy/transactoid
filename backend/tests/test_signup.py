"""Signup service: solo-household provisioning and identity resolution."""

from __future__ import annotations

import pytest

from penny.adapters.db.models import Category, Household, User
from penny.db import get_db
from penny.households import (
    provision_solo_household,
    resolve_or_provision_identity,
)


def test_provision_creates_household_user_and_taxonomy(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = provision_solo_household(
            s, email="Sam@Example.com", external_auth_id="clerk_abc"
        )
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.email == "sam@example.com"
        assert u.household_id == hid
        assert u.external_auth_id == "clerk_abc"
        assert s.query(Category).filter(Category.household_id == hid).count() > 0


def test_provision_is_idempotent_on_email(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        a = provision_solo_household(s, email="sam@example.com", external_auth_id="c1")
    with get_db().session() as s:
        b = provision_solo_household(s, email="sam@example.com", external_auth_id="c1")
    assert a == b


def test_pending_invite_is_claimed_and_joins_that_household(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hh = Household(name="Inviter HH")
        s.add(hh)
        s.flush()
        s.add(
            User(
                household_id=hh.household_id,
                email="guest@example.com",
                external_auth_id=None,
            )
        )  # pending invite
        inviter_hid = hh.household_id
    with get_db().session() as s:
        hid, uid = resolve_or_provision_identity(
            s, email="guest@example.com", external_auth_id="clerk_guest"
        )
    assert hid == inviter_hid  # joined the inviter's household, no new one
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.external_auth_id == "clerk_guest"


def test_no_pending_row_provisions_solo(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = resolve_or_provision_identity(
            s, email="solo@example.com", external_auth_id="clerk_solo"
        )
        # brand-new solo household: the only user in it
        assert s.query(User).filter(User.household_id == hid).count() == 1


def test_development_relinks_row_with_stale_auth_subject(isolated_db):
    # A test branch recreated from prod carries prod-instance subjects; a local
    # sign-in presents the dev-instance subject for the same verified email.
    # In development (the PENNY_ENV default) the row is re-bound, not orphaned.
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = provision_solo_household(
            s, email="sam@example.com", external_auth_id="clerk_prod_sub"
        )
    with get_db().session() as s:
        got = resolve_or_provision_identity(
            s, email="sam@example.com", external_auth_id="clerk_dev_sub"
        )
    assert got == (hid, uid)
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.external_auth_id == "clerk_dev_sub"


def test_production_never_restamps_a_subject(isolated_db, monkeypatch):
    # In production subjects never legitimately drift (one Clerk instance), so
    # a mismatched subject must not rebind the row. The email-idempotent
    # provision path still resolves to the same household; the stored subject
    # stays exactly as it was.
    monkeypatch.setenv("PENNY_ENV", "production")
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = provision_solo_household(
            s, email="sam@example.com", external_auth_id="clerk_prod_sub"
        )
    with get_db().session() as s:
        got = resolve_or_provision_identity(
            s, email="sam@example.com", external_auth_id="clerk_dev_sub"
        )
    assert got == (hid, uid)
    with get_db().session() as s:
        original = s.query(User).filter(User.user_id == uid).one()
        assert original.external_auth_id == "clerk_prod_sub"


def test_invalid_penny_env_raises(monkeypatch):
    from penny.config import penny_env

    monkeypatch.setenv("PENNY_ENV", "staging")
    with pytest.raises(ValueError, match="PENNY_ENV"):
        penny_env()
