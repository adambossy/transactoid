"""Signup service: solo-household provisioning and identity resolution."""

from __future__ import annotations

from penny.adapters.db.models import Category, User
from penny.db import get_db
from penny.signup import provision_solo_household


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
