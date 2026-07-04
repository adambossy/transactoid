"""/api/me/billing + connect route: masked reads, the secret never in the body."""

from __future__ import annotations

import pytest

import penny.api.main as main

_KEY = "sk-user-secret-abcd9999"


@pytest.fixture
def client(isolated_db: None, monkeypatch: pytest.MonkeyPatch):
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    # Dev auth mode (conftest pins PENNY_DEV_* principal); startup builds schema.
    with TestClient(main.app) as c:
        yield c


def test_billing_empty_state(client) -> None:
    r = client.get("/api/me/billing")
    assert r.status_code == 200
    body = r.json()
    assert body["remaining_cents"] == 0
    assert body["provider"] == "subsidy"
    assert body["credentials"] == []


def test_connect_key_then_masked_billing_never_leaks_secret(client) -> None:
    r = client.post(
        "/api/providers/google/key",
        json={"provider": "google", "key": _KEY},
    )
    assert r.status_code == 200
    assert _KEY not in r.text  # connect response never echoes the key

    r = client.get("/api/me/billing")
    assert r.status_code == 200
    body = r.json()
    assert _KEY not in r.text  # billing view never contains the secret
    assert body["provider"] == "google"  # now a connected BYO provider
    assert len(body["credentials"]) == 1
    assert body["credentials"][0]["hint"] == "sk-…9999"


def test_disconnect_removes_credential(client) -> None:
    client.post("/api/providers/google/key", json={"provider": "google", "key": _KEY})
    r = client.delete("/api/providers/google")
    assert r.status_code == 200
    body = client.get("/api/me/billing").json()
    assert body["credentials"] == []
    assert body["provider"] == "subsidy"
