"""Vault: encrypt-at-rest, masked reads never leak the key, per-user isolation."""

from __future__ import annotations

import uuid

from agent_harness.core.credentials import ApiKeyCredential
import pytest

from penny.api.persistence.engine import create_web_schema
from penny.billing import vault
from penny.billing.session import BillingSession
from penny.tenancy.context import RequestContext

_KEY = "sk-super-secret-abcd1234"


@pytest.fixture
def _cipher_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())


def _ctx(user: str) -> RequestContext:
    return RequestContext(
        user_id=uuid.UUID(user),
        household_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )


def test_upsert_then_masked_never_exposes_the_key(
    isolated_db: None, _cipher_key: None
) -> None:
    create_web_schema()
    ctx = _ctx("11111111-1111-1111-1111-111111111111")
    billing = BillingSession()
    with billing.begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key=_KEY)
    with billing.begin(ctx) as s:
        rows = vault.masked(s, ctx)
    assert len(rows) == 1
    assert rows[0]["provider"] == "google"
    assert rows[0]["hint"] == "sk-…1234"
    # The plaintext key appears nowhere in the masked view.
    assert _KEY not in str(rows)


def test_get_credential_round_trips_the_key(
    isolated_db: None, _cipher_key: None
) -> None:
    create_web_schema()
    ctx = _ctx("11111111-1111-1111-1111-111111111111")
    billing = BillingSession()
    with billing.begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key=_KEY)
    with billing.begin(ctx) as s:
        cred = vault.get_credential(s, ctx, provider="google")
    assert cred == ApiKeyCredential(provider="google", key=_KEY)


def test_ciphertext_at_rest_is_not_the_plaintext(
    isolated_db: None, _cipher_key: None
) -> None:
    create_web_schema()
    ctx = _ctx("11111111-1111-1111-1111-111111111111")
    billing = BillingSession()
    with billing.begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key=_KEY)
    with billing.begin(ctx) as s:
        from penny.billing.models import UserCredential

        row = s.query(UserCredential).one()
        assert _KEY not in row.secret_ciphertext
        assert row.secret_ciphertext.startswith("v1:")


def test_upsert_replaces_in_place(isolated_db: None, _cipher_key: None) -> None:
    create_web_schema()
    ctx = _ctx("11111111-1111-1111-1111-111111111111")
    billing = BillingSession()
    with billing.begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key=_KEY)
        vault.upsert_api_key(s, ctx, provider="google", key="sk-new-key-9999")
    with billing.begin(ctx) as s:
        cred = vault.get_credential(s, ctx, provider="google")
        rows = vault.masked(s, ctx)
    assert cred == ApiKeyCredential(provider="google", key="sk-new-key-9999")
    assert len(rows) == 1  # replaced, not duplicated


def test_second_user_cannot_read_first_users_credential(
    isolated_db: None, _cipher_key: None
) -> None:
    """App-layer isolation on SQLite (raw-SQL RLS isolation is the pg suite)."""
    create_web_schema()
    alice = _ctx("11111111-1111-1111-1111-111111111111")
    bob = _ctx("33333333-3333-3333-3333-333333333333")
    billing = BillingSession()
    with billing.begin(alice) as s:
        vault.upsert_api_key(s, alice, provider="google", key=_KEY)
    with billing.begin(bob) as s:
        assert vault.get_credential(s, bob, provider="google") is None
        assert vault.masked(s, bob) == []


def test_remove_is_idempotent(isolated_db: None, _cipher_key: None) -> None:
    create_web_schema()
    ctx = _ctx("11111111-1111-1111-1111-111111111111")
    billing = BillingSession()
    with billing.begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key=_KEY)
    with billing.begin(ctx) as s:
        vault.remove(s, ctx, provider="google")
    with billing.begin(ctx) as s:
        vault.remove(s, ctx, provider="google")  # no-op, no error
        assert vault.get_credential(s, ctx, provider="google") is None
