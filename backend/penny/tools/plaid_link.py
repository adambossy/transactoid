"""Agent tool: offer an inline hosted Plaid Link card.

Returns the link-token structured content the frontend ``PlaidLinkCard`` renderer
consumes (generative UI). The server-side ``public_token`` exchange is NOT here —
it is a website route (``POST /api/plaid/exchange``) the card calls on success,
keeping the token exchange and finance writes off the agent surface.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.tenancy.context import require_request_context
from penny.tools._services.plaid_link import create_link_token


@tool
async def connect_bank_account() -> dict[str, Any]:
    """Offer the user an inline card to connect a bank account via Plaid.

    Use when the user has no bank linked, or asks to connect (or add) one.
    Returns the Plaid link-token payload; the inline card handles the secure
    Plaid Link flow and the server exchanges the token. Tell the user a connect
    card is shown right in the chat.
    """
    ctx = require_request_context()
    return await asyncio.to_thread(create_link_token, user_id=ctx.user_id)
