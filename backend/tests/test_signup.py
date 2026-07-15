"""Signup service: solo-household provisioning and identity resolution."""

from __future__ import annotations

import pytest

from penny.adapters.db.models import Category, Household, User
from penny.db import get_db
from penny.households import (
    SubjectMismatchError,
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


def _provision_stale_subject_row():
    """A row provisioned under one Clerk instance's subject (as after a Neon
    test branch is recreated from prod)."""
    get_db().create_schema()
    with get_db().session() as s:
        return provision_solo_household(
            s, email="sam@example.com", external_auth_id="clerk_prod_sub"
        )


def test_development_relinks_row_with_stale_auth_subject(isolated_db, monkeypatch):
    # A local sign-in presents the dev-instance subject for the same verified
    # email; in development (the PENNY_ENV default) the row is re-bound.
    monkeypatch.delenv("PENNY_ENV", raising=False)
    hid, uid = _provision_stale_subject_row()
    with get_db().session() as s:
        got = resolve_or_provision_identity(
            s, email="sam@example.com", external_auth_id="clerk_dev_sub"
        )
    assert got == (hid, uid)
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.external_auth_id == "clerk_dev_sub"


def test_production_rejects_subject_mismatch(isolated_db, monkeypatch):
    # In production subjects never legitimately drift (one Clerk instance), so
    # a verified email bound to a different subject is a recycled-email
    # takeover shape: fail closed, row untouched.
    monkeypatch.setenv("PENNY_ENV", "production")
    hid, uid = _provision_stale_subject_row()
    with get_db().session() as s:
        with pytest.raises(SubjectMismatchError):
            resolve_or_provision_identity(
                s, email="sam@example.com", external_auth_id="clerk_dev_sub"
            )
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.external_auth_id == "clerk_prod_sub"


def test_relink_matches_legacy_mixed_case_email(isolated_db, monkeypatch):
    # Legacy rows may store mixed-case emails; resolution compares lowercased.
    monkeypatch.delenv("PENNY_ENV", raising=False)
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = provision_solo_household(
            s, email="sam@example.com", external_auth_id="clerk_prod_sub"
        )
        s.query(User).filter(User.user_id == uid).one().email = "Sam@Example.com"
    with get_db().session() as s:
        got = resolve_or_provision_identity(
            s, email="sam@example.com", external_auth_id="clerk_dev_sub"
        )
    assert got == (hid, uid)


def test_invalid_penny_env_raises(monkeypatch):
    from penny.config import penny_env

    monkeypatch.setenv("PENNY_ENV", "staging")
    with pytest.raises(ValueError, match="PENNY_ENV"):
        penny_env()
