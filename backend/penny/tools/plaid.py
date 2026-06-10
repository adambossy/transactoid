"""Plaid-facing tools.

The Plaid Link flow currently runs locally on ``https://localhost:8443``
and pops the user's browser via ``webbrowser.open``. This works for dev on
the maintainer's machine but is incompatible with a remote sandbox — the
productionization plan ([[productionize-transactoid]] B-6) covers
re-architecting the OAuth callback through a centralized public endpoint.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.adapters.clients.plaid import PlaidClient
from penny.db import get_db


def _item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "institution_id": getattr(item, "institution_id", None),
        "institution_name": getattr(item, "institution_name", None),
        "sync_cursor": getattr(item, "sync_cursor", None),
        "created_at": item.created_at.isoformat()
        if getattr(item, "created_at", None)
        else None,
    }


@tool
async def list_plaid_accounts() -> dict[str, Any]:
    """List every Plaid item (bank/card connection) the user has linked.

    Returns ``{"items": [...], "count": N}``. Empty when nothing is connected.
    """

    def _fetch() -> list[Any]:
        return get_db().list_plaid_items()

    items = await asyncio.to_thread(_fetch)
    return {"items": [_item_to_dict(it) for it in items], "count": len(items)}


@tool
async def connect_new_account() -> dict[str, Any]:
    """Connect a new bank/card via Plaid Link.

    Opens a local browser to the Plaid Link flow, waits for the user to
    finish OAuth, exchanges the public token for an access token, and
    persists the connection. Blocks until the user completes the flow (or
    a timeout fires inside the client). Tell the user to expect a browser
    window.

    Returns ``{"status": "success", "item_id", "institution_name", ...}``
    or ``{"status": "error", "message"}`` on failure.
    """

    def _connect() -> dict[str, Any]:
        try:
            plaid_client = PlaidClient.from_env()
            return plaid_client.connect_new_account(db=get_db())
        except Exception as exc:
            return {"status": "error", "message": f"Failed to connect account: {exc}"}

    return await asyncio.to_thread(_connect)
