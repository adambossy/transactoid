"""GET /api/household/members: shape, tenancy, and the initials fallback.

Clerk caching/degradation live in the adapter (``fetch_cached_user_profile``,
covered by ``tests/adapters/test_clerk.py``); these route tests inject plain
fake profile fetchers via ``get_profile_fetcher``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penny.adapters.clerk import EMPTY_PROFILE
from penny.adapters.db.models import Household, User
from penny.api.auth import request_context
from penny.api.household_routes import get_profile_fetcher, router
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode


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
        "c_ada": {"image_url": "https://img.clerk.com/ada", "first_name": "Ada"},
        "c_sam": EMPTY_PROFILE,
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
    r = _client(ctx, lambda sub: EMPTY_PROFILE).get("/api/household/members")

    # expected: only the caller's household's members
    assert sorted(m["email"] for m in r.json()["members"]) == ["ada@x.com", "sam@x.com"]
