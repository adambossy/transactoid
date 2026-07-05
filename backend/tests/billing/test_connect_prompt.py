"""Blocked gate enqueues one byo_credential reminder; the tool returns options."""

from __future__ import annotations

import uuid

import pytest

from penny.billing import reminders
from penny.tools.connect_provider import connect_provider

_USER = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def _clear_reminders() -> None:
    reminders.clear(_USER)
    yield
    reminders.clear(_USER)


def test_blocked_enqueues_exactly_one_reminder() -> None:
    assert reminders.enqueue_byo_credential(_USER) is True
    # Re-blocking the same user does not stack reminders.
    assert reminders.enqueue_byo_credential(_USER) is False
    assert reminders.has_pending(_USER) is True
    assert reminders.kind() == "byo_credential"


def test_clear_removes_pending_reminder() -> None:
    reminders.enqueue_byo_credential(_USER)
    reminders.clear(_USER)
    assert reminders.has_pending(_USER) is False


@pytest.mark.asyncio
async def test_connect_tool_returns_provider_options() -> None:
    result = await connect_provider.fn()
    assert result["type"] == "connect_provider"
    ids = {p["id"] for p in result["providers"]}
    assert {"google", "openai", "anthropic"} <= ids
    assert result["settings_url"] == "/settings/providers"
