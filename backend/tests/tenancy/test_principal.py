import uuid

import pytest

from penny.tenancy.context import SessionMode
from penny.tenancy.principal import resolve_dev_principal

U = "11111111-1111-1111-1111-111111111111"
H = "22222222-2222-2222-2222-222222222222"


def test_resolves_from_headers():
    ctx = resolve_dev_principal(
        {
            "X-Penny-User-Id": U,
            "X-Penny-Household-Id": H,
            "X-Penny-Session-Mode": "joint",
        }
    )
    assert ctx.user_id == uuid.UUID(U)
    assert ctx.household_id == uuid.UUID(H)
    assert ctx.session_mode is SessionMode.JOINT


def test_header_case_insensitive_and_defaults_to_individual():
    ctx = resolve_dev_principal({"x-penny-user-id": U, "x-penny-household-id": H})
    assert ctx.session_mode is SessionMode.INDIVIDUAL


def test_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("PENNY_DEV_USER_ID", U)
    monkeypatch.setenv("PENNY_DEV_HOUSEHOLD_ID", H)
    ctx = resolve_dev_principal({})
    assert ctx.user_id == uuid.UUID(U)


def test_raises_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PENNY_DEV_USER_ID", raising=False)
    monkeypatch.delenv("PENNY_DEV_HOUSEHOLD_ID", raising=False)
    with pytest.raises(ValueError):
        resolve_dev_principal({})
