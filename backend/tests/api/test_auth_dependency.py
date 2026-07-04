import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import penny.api.auth as api_auth
from penny.api.auth import request_context
from penny.auth.jwt_verifier import TokenError
from penny.auth.settings import AuthSettings
from penny.tenancy.context import RequestContext

CLERK = AuthSettings(
    mode="clerk",
    issuer="https://iss",
    jwks_url="https://iss/jwks",
    audience=None,
    frontend_origin="https://app",
)


class FakeVerifier:
    def __init__(self, claims=None):
        self._claims = claims

    def verify(self, token):
        if self._claims is None:
            raise TokenError("bad token")
        return self._claims


def _app(monkeypatch, verifier, settings=CLERK):
    monkeypatch.setattr(api_auth, "get_auth_settings", lambda: settings)
    monkeypatch.setattr(api_auth, "get_verifier", lambda: verifier)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(ctx: RequestContext = Depends(request_context)):
        return {"user_id": str(ctx.user_id)}

    return app


def test_missing_bearer_is_401(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier()))
    assert client.get("/whoami").status_code == 401


def test_invalid_token_is_401(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier(claims=None)))
    r = client.get("/whoami", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_verified_unknown_user_is_provisioned(monkeypatch, isolated_db):
    # Phase 4 open signup: a verified identity with no row is auto-provisioned a
    # solo household rather than rejected with 403 (the phase-2 behaviour).
    from penny.db import get_db

    get_db().create_schema()
    verifier = FakeVerifier(
        claims={"sub": "stranger", "email": "s@x.com", "email_verified": True}
    )
    client = TestClient(_app(monkeypatch, verifier))
    r = client.get("/whoami", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["user_id"]


def test_unverified_unknown_user_is_403(monkeypatch, isolated_db):
    # Fail closed: an unverified email is never provisioned an account.
    from penny.db import get_db

    get_db().create_schema()
    verifier = FakeVerifier(
        claims={"sub": "stranger2", "email": "s2@x.com", "email_verified": False}
    )
    client = TestClient(_app(monkeypatch, verifier))
    r = client.get("/whoami", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403


def test_clerk_mode_ignores_spoofed_dev_headers(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier(claims=None)))
    r = client.get(
        "/whoami",
        headers={
            "X-Penny-User-Id": str(uuid.uuid4()),
            "X-Penny-Household-Id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 401  # headers do nothing without a valid bearer
