import pytest

from penny.auth.settings import load_auth_settings

CLERK_ENV = {
    "PENNY_CLERK_ISSUER": "https://x.clerk.accounts.dev",
    "PENNY_CLERK_JWKS_URL": "https://x.clerk.accounts.dev/.well-known/jwks.json",
    "PENNY_FRONTEND_ORIGIN": "https://penny.example.com",
}


def _clear(monkeypatch):
    for k in ["PENNY_AUTH_MODE", *CLERK_ENV, "PENNY_CLERK_AUDIENCE"]:
        monkeypatch.delenv(k, raising=False)


def test_defaults_to_clerk_and_fails_without_config(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(RuntimeError):
        load_auth_settings()  # clerk mode, missing issuer/jwks/origin


def test_clerk_mode_loads_with_full_config(monkeypatch):
    _clear(monkeypatch)
    for k, v in CLERK_ENV.items():
        monkeypatch.setenv(k, v)
    s = load_auth_settings()
    assert s.mode == "clerk"
    assert s.issuer == CLERK_ENV["PENNY_CLERK_ISSUER"]


def test_invalid_mode_rejected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("PENNY_AUTH_MODE", "off")
    with pytest.raises(RuntimeError):
        load_auth_settings()


def test_dev_mode_allowed_without_clerk_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("PENNY_AUTH_MODE", "dev")
    assert load_auth_settings().mode == "dev"
