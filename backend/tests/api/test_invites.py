"""Invite service: pending-row creation, list, revoke, and guards."""

from __future__ import annotations

import pytest

from penny.adapters.db.models import Household, User
from penny.db import get_db
from penny.signup import InviteError, create_invite
from penny.tenancy.context import RequestContext, SessionMode


class FakeClerkInvites:
    def __init__(self):
        self.sent: list[str] = []

    def create_invitation(self, email):
        self.sent.append(email)

    def revoke_invitation(self, email):
        self.sent.remove(email)


def _ctx(hid, uid):
    return RequestContext(
        user_id=uid, household_id=hid, session_mode=SessionMode.INDIVIDUAL
    )


def _seed_member(db):
    """Create a household with one active member; return (ctx, clerk_fake)."""
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u)
        s.flush()
        return _ctx(hh.household_id, u.user_id)


def _client(ctx, clerk):
    """A TestClient over a minimal app mounting only the signup router, with the
    auth principal + Clerk provider overridden (no startup/bootstrap side effects).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from penny.api.auth import request_context
    from penny.api.signup_routes import get_clerk_invites, router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[request_context] = lambda: ctx
    app.dependency_overrides[get_clerk_invites] = lambda: clerk
    return TestClient(app)


def test_create_invite_makes_pending_row_and_calls_clerk(isolated_db):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u)
        s.flush()
        hid, uid = hh.household_id, u.user_id
    clerk = FakeClerkInvites()
    with db.session_for(_ctx(hid, uid)) as s:
        create_invite(s, _ctx(hid, uid), email="Guest@X.com", clerk=clerk)
    assert clerk.sent == ["guest@x.com"]
    with db.session() as s:
        p = s.query(User).filter(User.email == "guest@x.com").one()
        assert p.household_id == hid and p.external_auth_id is None


def test_invite_rejects_active_account(isolated_db):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        other = User(
            household_id=hh.household_id, email="taken@x.com", external_auth_id="c2"
        )
        s.add_all([u, other])
        s.flush()
        hid, uid = hh.household_id, u.user_id
    with pytest.raises(InviteError):
        with db.session_for(_ctx(hid, uid)) as s:
            create_invite(
                s, _ctx(hid, uid), email="taken@x.com", clerk=FakeClerkInvites()
            )


def test_post_invites_route_returns_201(isolated_db):
    db = get_db()
    db.create_schema()
    ctx = _seed_member(db)
    clerk = FakeClerkInvites()
    r = _client(ctx, clerk).post("/api/invites", json={"email": "New@X.com"})
    assert r.status_code == 201
    assert r.json()["email"] == "new@x.com"
    assert clerk.sent == ["new@x.com"]


def test_post_invites_route_409_on_active_email(isolated_db):
    db = get_db()
    db.create_schema()
    ctx = _seed_member(db)
    with db.session_for(ctx) as s:
        s.add(
            User(
                household_id=ctx.household_id,
                email="taken@x.com",
                external_auth_id="c9",
            )
        )
    r = _client(ctx, FakeClerkInvites()).post(
        "/api/invites", json={"email": "taken@x.com"}
    )
    assert r.status_code == 409
