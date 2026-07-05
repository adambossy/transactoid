"""OAuth: PKCE + CSRF state, mismatch rejection, store + atomic refresh rotation."""

from __future__ import annotations

import urllib.parse
import uuid

from agent_harness.core.credentials import OAuthCredential
import pytest

from penny.api.persistence.engine import create_web_schema
from penny.billing import oauth, vault
from penny.billing.oauth import OAuthError
from penny.billing.session import BillingSession
from penny.tenancy.context import RequestContext

_PROVIDER = "testprov"


@pytest.fixture(autouse=True)
def _oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PENNY_OAUTH_TESTPROV_CLIENT_ID", "client-123")
    monkeypatch.setenv("PENNY_OAUTH_TESTPROV_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setenv(
        "PENNY_OAUTH_TESTPROV_AUTHORIZE_URL", "https://provider.example/authorize"
    )
    monkeypatch.setenv(
        "PENNY_OAUTH_TESTPROV_TOKEN_URL", "https://provider.example/token"
    )
    monkeypatch.setenv(
        "PENNY_OAUTH_TESTPROV_REDIRECT_URI", "https://penny.example/oauth/callback"
    )
    monkeypatch.setenv("PENNY_OAUTH_TESTPROV_SCOPES", "read write")


def _ctx() -> RequestContext:
    return RequestContext(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        household_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )


def _parse_state_and_challenge(url: str) -> dict[str, str]:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return {k: v[0] for k, v in q.items()}


def test_start_returns_url_with_distinct_state_and_challenge(isolated_db: None) -> None:
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        r1 = oauth.start(s, ctx, provider=_PROVIDER)
        r2 = oauth.start(s, ctx, provider=_PROVIDER)
    p1 = _parse_state_and_challenge(r1["authorize_url"])
    p2 = _parse_state_and_challenge(r2["authorize_url"])
    assert p1["code_challenge_method"] == "S256"
    assert p1["code_challenge"] and p1["state"]
    # State and challenge are fresh per call (no reuse of the PKCE verifier).
    assert p1["state"] != p2["state"]
    assert p1["code_challenge"] != p2["code_challenge"]


def test_callback_with_mismatched_state_is_rejected(isolated_db: None) -> None:
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        oauth.start(s, ctx, provider=_PROVIDER)
        with pytest.raises(OAuthError):
            oauth.callback(
                s,
                ctx,
                provider=_PROVIDER,
                code="authcode",
                state="not-the-real-state",
                exchanger=lambda config, form: {"access_token": "nope"},
            )


def test_valid_callback_stores_oauth_credential(isolated_db: None) -> None:
    create_web_schema()
    ctx = _ctx()

    def _fake_exchange(config, form):
        assert form["grant_type"] == "authorization_code"
        assert form["code_verifier"]  # PKCE verifier round-tripped
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
        }

    with BillingSession().begin(ctx) as s:
        state = _parse_state_and_challenge(
            oauth.start(s, ctx, provider=_PROVIDER)["authorize_url"]
        )["state"]
        oauth.callback(
            s,
            ctx,
            provider=_PROVIDER,
            code="authcode",
            state=state,
            exchanger=_fake_exchange,
        )
    with BillingSession().begin(ctx) as s:
        cred = vault.get_credential(s, ctx, provider=_PROVIDER)
    assert isinstance(cred, OAuthCredential)
    assert cred.access_token == "access-1"
    assert cred.refresh_token == "refresh-1"


def test_refresh_rotates_and_persists_new_refresh_token(isolated_db: None) -> None:
    create_web_schema()
    ctx = _ctx()
    # Seed an about-to-expire oauth credential.
    with BillingSession().begin(ctx) as s:
        vault.upsert_oauth(
            s,
            ctx,
            provider=_PROVIDER,
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=0.0,  # long expired → refresh fires
        )

    def _fake_refresh(config, form):
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "old-refresh"
        return {
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }

    with BillingSession().begin(ctx) as s:
        did = oauth.refresh(s, ctx, provider=_PROVIDER, exchanger=_fake_refresh)
    assert did is True
    with BillingSession().begin(ctx) as s:
        cred = vault.get_credential(s, ctx, provider=_PROVIDER)
    assert cred.access_token == "new-access"
    assert cred.refresh_token == "rotated-refresh"  # rotation persisted


def test_refresh_noop_when_still_fresh(isolated_db: None) -> None:
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        vault.upsert_oauth(
            s,
            ctx,
            provider=_PROVIDER,
            access_token="a",
            refresh_token="r",
            expires_at=1_000_000_000_000.0,
        )
    with BillingSession().begin(ctx) as s:
        did = oauth.refresh(
            s,
            ctx,
            provider=_PROVIDER,
            exchanger=lambda config, form: pytest.fail("should not exchange"),
            now=0.0,
        )
    assert did is False
