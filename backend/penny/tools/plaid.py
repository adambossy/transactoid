"""Plaid-facing tools — phase 1 surface (read-only listings).

``connect_new_account`` and ``sync_transactions`` ship in phase 2 once the
Plaid client + categorizer + persister are in place.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from ..db import get_db


def _item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "institution_id": getattr(item, "institution_id", None),
        "institution_name": getattr(item, "institution_name", None),
        "sync_cursor": getattr(item, "sync_cursor", None),
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else None,
    }


@tool
async def list_plaid_accounts() -> dict[str, Any]:
    """List every Plaid item (bank/card connection) the user has linked.

    Returns a dict with ``items`` (list of connection summaries) and ``count``.
    Returns an empty list when no accounts are connected.
    """

    def _fetch() -> list[Any]:
        return get_db().list_plaid_items()

    items = await asyncio.to_thread(_fetch)
    return {"items": [_item_to_dict(it) for it in items], "count": len(items)}
