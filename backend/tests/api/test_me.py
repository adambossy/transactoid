"""/api/me bootstrap + PATCH /api/household rename."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penny.adapters.db.models import Household, User
from penny.api.auth import request_context
from penny.api.signup_routes import router
from penny.db import get_db
from penny.signup import rename_household
from penny.tenancy.context import RequestContext, SessionMode


def _ctx(hid, uid):
    return RequestContext(
        user_id=uid, household_id=hid, session_mode=SessionMode.INDIVIDUAL
    )


def _seed(db, *, name="old"):
    with db.session() as s:
        hh = Household(name=name)
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u)
        s.flush()
        return _ctx(hh.household_id, u.user_id)


def _client(ctx):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[request_context] = lambda: ctx
    return TestClient(app)


def test_rename_household(isolated_db):
    db = get_db()
    db.create_schema()
    ctx = _seed(db)
    with db.session_for(ctx) as s:
        rename_household(s, ctx, name="Bossy Household")
    with db.session() as s:
        got = (
            s.query(Household).filter(Household.household_id == ctx.household_id).one()
        )
        assert got.name == "Bossy Household"


def test_get_me_returns_user_and_household(isolated_db):
    db = get_db()
    db.create_schema()
    ctx = _seed(db, name="Home")
    r = _client(ctx).get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(ctx.user_id)
    assert body["email"] == "me@x.com"
    assert body["household_id"] == str(ctx.household_id)
    assert body["household_name"] == "Home"


def test_patch_household_route(isolated_db):
    db = get_db()
    db.create_schema()
    ctx = _seed(db)
    r = _client(ctx).patch("/api/household", json={"name": "Renamed"})
    assert r.status_code == 200
    assert _client(ctx).get("/api/me").json()["household_name"] == "Renamed"
