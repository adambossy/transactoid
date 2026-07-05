import pytest

from penny.adapters.db.models import Household, User
from penny.auth.identity import UnknownUserError, link_or_resolve_user
from penny.db import get_db


def _seed_user(email: str, sub: str | None):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email=email, external_auth_id=sub)
        s.add(u)
        s.flush()
        return hh.household_id, u.user_id


def test_resolves_by_sub(isolated_db):
    hid, uid = _seed_user("a@x.com", "sub_1")
    with get_db().session() as s:
        assert link_or_resolve_user(
            s, sub="sub_1", email=None, email_verified=False
        ) == (
            hid,
            uid,
        )


def test_first_login_links_by_verified_email_case_insensitive(isolated_db):
    hid, uid = _seed_user("a@x.com", None)
    with get_db().session() as s:
        got = link_or_resolve_user(
            s, sub="sub_new", email="A@X.com", email_verified=True
        )
    assert got == (hid, uid)
    with get_db().session() as s:
        assert (
            s.query(User).filter(User.user_id == uid).one().external_auth_id
            == "sub_new"
        )


def test_unverified_email_cannot_link(isolated_db):
    _seed_user("a@x.com", None)
    with get_db().session() as s, pytest.raises(UnknownUserError):
        link_or_resolve_user(s, sub="sub_new", email="a@x.com", email_verified=False)


def test_unknown_user_rejected(isolated_db):
    _seed_user("a@x.com", "sub_1")
    with get_db().session() as s, pytest.raises(UnknownUserError):
        link_or_resolve_user(s, sub="stranger", email="who@x.com", email_verified=True)
