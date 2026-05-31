"""Plaid sync — fetch transactions across all connected items, categorize, persist.

Thin ``@tool`` wrapper over ``SyncTool`` (which itself orchestrates
``PlaidClient`` -> ``Categorizer`` -> ``PersistTool``). Cursor persistence
and dedup live inside the service layer.
"""

from __future__ import annotations

from typing import Any

from agent_harness import tool

from ..adapters.clients.plaid import PlaidClient
from ..db import get_db
from ..services import build_categorizer, get_taxonomy
from ..tools._services.sync_service import SyncTool


@tool
async def sync_transactions(count: int = 250) -> dict[str, Any]:
    """Sync the latest transactions from every connected Plaid item.

    Categorizes new and modified transactions and persists them. Cursor
    state is tracked per item so subsequent calls are incremental.

    Args:
        count: Max transactions per page. Default 250.

    Returns:
        ``{"status": "success", "items_synced", "total_added",
        "total_modified", "total_removed", ...}`` on success, or
        ``{"status": "error", "message": ...}`` on failure.
    """
    try:
        plaid_client = PlaidClient.from_env()
        sync_service = SyncTool(
            plaid_client=plaid_client,
            categorizer_factory=build_categorizer,
            db=get_db(),
            taxonomy=get_taxonomy(),
        )
        summary = await sync_service.sync(count=count)
        return {"status": "success", **summary.to_dict()}
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "items_synced": 0,
            "total_added": 0,
            "total_modified": 0,
            "total_removed": 0,
        }
