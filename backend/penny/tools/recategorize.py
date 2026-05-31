"""Recategorize a merchant and tag transactions in bulk."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from ..services import get_persister, get_taxonomy


@tool
async def recategorize_merchant(merchant_id: int, category_key: str) -> dict[str, Any]:
    """Move every transaction for a merchant to a new category.

    Args:
        merchant_id: The merchant to recategorize.
        category_key: The target category key (e.g. ``food_and_dining.groceries``).
            Must be a key in the live taxonomy.
    """

    def _run() -> dict[str, Any]:
        if not get_taxonomy().is_valid_key(category_key):
            return {
                "status": "error",
                "message": f"Invalid category key: {category_key}",
                "updated": 0,
            }
        try:
            updated = get_persister().recategorize_merchant(
                merchant_id=merchant_id, category_key=category_key
            )
            return {
                "status": "success",
                "updated": updated,
                "message": f"Recategorized {updated} transactions to {category_key}",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc), "updated": 0}

    return await asyncio.to_thread(_run)


@tool
async def tag_transactions(transaction_ids: list[int], tags: list[str]) -> dict[str, Any]:
    """Apply one or more tags to a list of transactions.

    Args:
        transaction_ids: Transaction IDs to tag.
        tags: Tag names to apply (created on first use).
    """

    def _run() -> dict[str, Any]:
        try:
            result = get_persister().apply_tags(transaction_ids, tags)
            return {
                "status": "success",
                "applied": result.applied,
                "created_tags": result.created_tags,
                "message": f"Applied {len(tags)} tags to {result.applied} transactions",
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": str(exc),
                "applied": 0,
                "created_tags": [],
            }

    return await asyncio.to_thread(_run)
