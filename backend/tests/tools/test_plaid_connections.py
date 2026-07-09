"""Tool-shape tests for the Plaid connection-health + relink tools.

`plaid_connection_status` classifies each item's live Plaid error_code into a
``needs_relink`` flag; `relink_account` mints an update-mode link token for an
existing item (and errors on an unknown one). Both run against a fake Plaid
client — no real Plaid — with the @tool wrappers invoked via ``.fn()``.
"""

from __future__ import annotations

import uuid

import pytest

from penny.adapters.db.models import Household, PlaidItem, User
from penny.db import get_db
from penny.tenancy.context import (
    RequestContext,
    reset_request_context,
    set_request_context,
)
from penny.tools import plaid as plaid_tools, plaid_link as plaid_link_tools
from penny.tools._services import plaid_link as plaid_link_service


def _seed_item(*, item_id: str, institution_name: str | None) -> RequestContext:
    """Seed a household/user + one PlaidItem, returning that principal's context."""
    db = get_db()
    db.create_schema()
    hh = uuid.uuid4()
    u = uuid.uuid4()
    with db.session() as s:
        s.add(Household(household_id=hh, name="H"))
        s.flush()
        s.add(User(user_id=u, household_id=hh, email="a@x.com"))
        s.flush()
        s.add(
            PlaidItem(
                item_id=item_id,
                access_token="enc-token",
                institution_id="ins_1",
                institution_name=institution_name,
                household_id=hh,
                owner_user_id=u,
            )
        )
        s.flush()
    return RequestContext(user_id=u, household_id=hh)


class _FakeStatusClient:
    """Fake PlaidClient returning a preset error_code per access token."""

    def __init__(self, error_code: str | None) -> None:
        self._error_code = error_code

    def get_item_status(self, access_token: str) -> str | None:  # noqa: ARG002
        return self._error_code


class _FakeLinkClient:
    """Fake PlaidClient recording the update-mode link-token request."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_link_token(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "link-sandbox-update"


@pytest.mark.asyncio
async def test_connection_status_flags_login_required(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_item(item_id="item-1", institution_name="Alliant")
    monkeypatch.setattr(
        plaid_tools.PlaidClient,
        "from_env",
        classmethod(lambda cls: _FakeStatusClient("ITEM_LOGIN_REQUIRED")),
    )

    result = await plaid_tools.plaid_connection_status.fn()

    assert result["count"] == 1
    conn = result["connections"][0]
    assert conn["institution_name"] == "Alliant"
    assert conn["healthy"] is False
    assert conn["needs_relink"] is True
    assert conn["error_code"] == "ITEM_LOGIN_REQUIRED"
    assert result["needs_relink"] == ["Alliant"]


@pytest.mark.asyncio
async def test_connection_status_healthy_item(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_item(item_id="item-1", institution_name="Chase")
    monkeypatch.setattr(
        plaid_tools.PlaidClient,
        "from_env",
        classmethod(lambda cls: _FakeStatusClient(None)),
    )

    result = await plaid_tools.plaid_connection_status.fn()

    conn = result["connections"][0]
    assert conn["healthy"] is True
    assert conn["needs_relink"] is False
    assert conn["error_code"] is None
    assert result["needs_relink"] == []


@pytest.mark.asyncio
async def test_relink_account_mints_update_token(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _seed_item(item_id="item-1", institution_name="Alliant")
    fake = _FakeLinkClient()
    monkeypatch.setenv("PENNY_PLAID_LINK_MODE", "hosted")
    monkeypatch.setattr(
        plaid_link_service.PlaidClient, "from_env", classmethod(lambda cls: fake)
    )

    token = set_request_context(ctx)
    try:
        result = await plaid_link_tools.relink_account.fn(item_id="item-1")
    finally:
        reset_request_context(token)

    assert result["mode"] == "update"
    assert result["link_token"] == "link-sandbox-update"
    assert result["item_id"] == "item-1"
    assert result["institution_name"] == "Alliant"
    # Update mode passes the existing access token and no products.
    assert fake.calls and fake.calls[0]["access_token"] == "enc-token"


@pytest.mark.asyncio
async def test_relink_account_unknown_item_errors(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _seed_item(item_id="item-1", institution_name="Alliant")
    monkeypatch.setenv("PENNY_PLAID_LINK_MODE", "hosted")

    token = set_request_context(ctx)
    try:
        result = await plaid_link_tools.relink_account.fn(item_id="does-not-exist")
    finally:
        reset_request_context(token)

    assert result["status"] == "error"
    assert "does-not-exist" in result["message"]
