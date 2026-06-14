"""Recategorize a merchant and tag transactions in bulk."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.services import get_persister, get_taxonomy


@tool
async def recategorize_merchant(
    merchant_id: int, category_key: str, reason: str
) -> dict[str, Any]:
    """Move every unverified transaction for a merchant to a new category.

    Args:
        merchant_id: The merchant to recategorize.
        category_key: The target category key (e.g. ``food_and_dining.groceries``).
            Must be a key in the live taxonomy.
        reason: A concise, one-sentence natural-language explanation of WHY the
            user wants this change, derived from the conversation (e.g. "User says
            Jubilee Market is their neighborhood grocer, not a restaurant"). This is
            written to the audit log so future categorization decisions can be
            debugged. Summarize the user's intent even if they did not state it
            explicitly.
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
                merchant_id=merchant_id, category_key=category_key, reason=reason
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
async def recategorize_transaction(
    transaction_id: int, category_key: str, reason: str
) -> dict[str, Any]:
    """Recategorize a single (unverified) transaction.

    Use this when the user wants to correct one specific transaction rather than
    every transaction for a merchant. Verified transactions cannot be changed.

    Args:
        transaction_id: The transaction to recategorize.
        category_key: The target category key (e.g. ``food_and_dining.groceries``).
            Must be a key in the live taxonomy.
        reason: A concise, one-sentence natural-language explanation of WHY the
            user wants this change, derived from the conversation. Written to the
            audit log so the original categorization can be debugged.
    """

    def _run() -> dict[str, Any]:
        if not get_taxonomy().is_valid_key(category_key):
            return {
                "status": "error",
                "message": f"Invalid category key: {category_key}",
            }
        try:
            get_persister().recategorize_transaction(
                transaction_id=transaction_id, category_key=category_key, reason=reason
            )
            return {
                "status": "success",
                "message": f"Recategorized transaction {transaction_id} to {category_key}",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)


@tool
async def tag_transactions(
    transaction_ids: list[int], tags: list[str]
) -> dict[str, Any]:
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
