"""Gate: BYO > subsidy > blocked, dev bypass, and grant-on-Plaid-link."""

from __future__ import annotations

import uuid

import pytest

from penny.api.persistence.engine import create_web_schema
from penny.billing import gate, metering, vault
from penny.billing.gate import Blocked, UseByo, UseDefault, UseSubsidy
from penny.billing.session import BillingSession
from penny.tenancy.context import RequestContext


@pytest.fixture
def _cipher_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())


def _ctx() -> RequestContext:
    return RequestContext(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        household_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )


def test_billing_disabled_uses_default(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PENNY_SUBSIDY_PROVIDER_KEY", raising=False)
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        assert isinstance(gate.resolve_for_run(s, ctx), UseDefault)


def test_remaining_positive_no_byo_uses_subsidy(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENNY_SUBSIDY_PROVIDER_KEY", "platform-key-xyz")
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        metering.grant_subsidy(s, ctx, cents=200)
    with BillingSession().begin(ctx) as s:
        decision = gate.resolve_for_run(s, ctx)
    assert decision == UseSubsidy(platform_key="platform-key-xyz")


def test_remaining_exhausted_no_byo_is_blocked(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENNY_SUBSIDY_PROVIDER_KEY", "platform-key-xyz")
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        metering.grant_subsidy(s, ctx, cents=0)  # granted but nothing remaining
    with BillingSession().begin(ctx) as s:
        assert isinstance(gate.resolve_for_run(s, ctx), Blocked)


def test_byo_wins_regardless_of_remaining(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch, _cipher_key: None
) -> None:
    monkeypatch.setenv("PENNY_SUBSIDY_PROVIDER_KEY", "platform-key-xyz")
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider="google", key="sk-user-own-1234")
        # No subsidy grant at all → remaining is 0, yet BYO must still win.
    with BillingSession().begin(ctx) as s:
        decision = gate.resolve_for_run(s, ctx)
    assert isinstance(decision, UseByo)
    assert decision.credential.provider == "google"


def test_grant_subsidy_on_plaid_link_is_idempotent(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENNY_SUBSIDY_CENTS", "200")
    create_web_schema()
    ctx = _ctx()
    with BillingSession().begin(ctx) as s:
        assert gate.grant_subsidy_on_plaid_link(s, ctx) is True
    with BillingSession().begin(ctx) as s:
        assert gate.grant_subsidy_on_plaid_link(s, ctx) is False  # once per user
    with BillingSession().begin(ctx) as s:
        assert metering.granted_cents(s, ctx) == 200
