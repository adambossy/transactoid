"""GET /api/household/members: live Clerk avatars, tenancy, cache, degradation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from penny.adapters.clerk import ClerkError
from penny.adapters.db.models import Household, User
from penny.api import signup_routes
from penny.api.auth import request_context
from penny.api.signup_routes import get_profile_fetcher, router
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode


@pytest.fixture(autouse=True)
def _fresh_profile_cache():
    """The TTL cache is module state; isolate it per test."""
    signup_routes._profile_cache.clear()
    yield
    signup_routes._profile_cache.clear()


def _ctx(hid, uid):
    return RequestContext(
        user_id=uid, household_id=hid, session_mode=SessionMode.INDIVIDUAL
    )


def _seed_household(db):
    """A household with two linked members and one pending invitee.

    Returns (ctx-as-first-member, second_member_user_id).
    """
    with db.session() as s:
        hh = Household(name="Home")
        s.add(hh)
        s.flush()
        me = User(
            household_id=hh.household_id, email="ada@x.com", external_auth_id="c_ada"
        )
        s.add(me)
        s.flush()
        partner = User(
            household_id=hh.household_id, email="sam@x.com", external_auth_id="c_sam"
        )
        pending = User(
            household_id=hh.household_id, email="kid@x.com", external_auth_id=None
        )
        s.add_all([partner, pending])
        s.flush()
        return _ctx(hh.household_id, me.user_id), partner.user_id


def _client(ctx, fetch_profile):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[request_context] = lambda: ctx
    app.dependency_overrides[get_profile_fetcher] = lambda: fetch_profile
    return TestClient(app)


def test_members_lists_linked_users_with_avatars(isolated_db):
    # input: two linked members (one with a Clerk image, one without) and a
    # pending invitee who must not appear.
    db = get_db()
    db.create_schema()
    ctx, partner_id = _seed_household(db)
    profiles = {
        "c_ada": {
            "image_url": "https://img.clerk.com/ada",
            "first_name": "Ada",
            "last_name": None,
        },
        "c_sam": {"image_url": None, "first_name": None, "last_name": None},
    }

    # act
    r = _client(ctx, lambda sub: profiles[sub]).get("/api/household/members")

    # expected: both linked members in creation order, pending invitee absent;
    # display_name is the Clerk first name or the email local-part.
    assert r.status_code == 200
    expected_members = [
        {
            "user_id": str(ctx.user_id),
            "email": "ada@x.com",
            "display_name": "Ada",
            "image_url": "https://img.clerk.com/ada",
            "is_you": True,
        },
        {
            "user_id": str(partner_id),
            "email": "sam@x.com",
            "display_name": "sam",
            "image_url": None,
            "is_you": False,
        },
    ]
    assert r.json() == {"members": expected_members}


def test_members_degrades_to_no_image_when_clerk_fails(isolated_db):
    # input: the profile fetch raises (Clerk down / no secret key in dev)
    db = get_db()
    db.create_schema()
    ctx, _ = _seed_household(db)

    def _broken(sub):
        raise ClerkError("CLERK_SECRET_KEY is not set")

    # act
    r = _client(ctx, _broken).get("/api/household/members")

    # expected: the route still answers; every member has a null image and an
    # email-derived display name (the client renders initials).
    assert r.status_code == 200
    output = [(m["display_name"], m["image_url"]) for m in r.json()["members"]]
    assert output == [("ada", None), ("sam", None)]


def test_members_never_leak_across_households(isolated_db):
    # input: a second household with its own member
    db = get_db()
    db.create_schema()
    ctx, _ = _seed_household(db)
    with db.session() as s:
        other_hh = Household(name="Elsewhere")
        s.add(other_hh)
        s.flush()
        s.add(
            User(
                household_id=other_hh.household_id,
                email="stranger@x.com",
                external_auth_id="c_stranger",
            )
        )

    # act
    r = _client(
        ctx, lambda sub: {"image_url": None, "first_name": None, "last_name": None}
    ).get("/api/household/members")

    # expected: only the caller's household's members
    assert sorted(m["email"] for m in r.json()["members"]) == ["ada@x.com", "sam@x.com"]


def test_members_profile_fetch_is_ttl_cached(isolated_db):
    # input: two requests within the TTL
    db = get_db()
    db.create_schema()
    ctx, _ = _seed_household(db)
    calls: list[str] = []

    def _counting(sub):
        calls.append(sub)
        return {"image_url": None, "first_name": None, "last_name": None}

    client = _client(ctx, _counting)

    # act
    client.get("/api/household/members")
    client.get("/api/household/members")

    # expected: one Clerk fetch per member, not per request
    assert sorted(calls) == ["c_ada", "c_sam"]
