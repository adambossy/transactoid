"""Agent tool: record a user's accept/decline of an onboarding nudge.

Thin ``@tool`` over the ``penny.onboarding`` service (website/app domain). The
tool does not touch the web store directly — it delegates the persistence
decision to the service, keeping the agent surface thin (decision D5). The tool
never *performs* the underlying action (linking a bank, editing taxonomy): those
are other tools. This only marks the nudge resolved so onboarding stops surfacing
it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.onboarding import resolve
from penny.tenancy.context import require_request_context


@tool
async def resolve_onboarding_item(item_key: str, action: str) -> dict[str, Any]:
    """Mark an onboarding step accepted or dismissed for the current user.

    Call when the user explicitly accepts or declines a setup nudge. ``item_key``
    is one of the onboarding steps (e.g. ``connect_plaid``); ``action`` is
    ``"accepted"`` or ``"dismissed"``. A dismissed step is never nudged again,
    but the user can always ask later and you perform the action directly.
    Returns ``{"item_key", "status"}`` (or ``{"error"}`` for a bad key/action).
    """
    ctx = require_request_context()
    return await asyncio.to_thread(resolve, ctx, item_key, action)
