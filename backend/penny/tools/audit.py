"""Read-only audit / history tools.

Thin ``@tool`` wrappers over the categorization read API on ``DB``. Used both by
the conversational chat agent (to debug categorizations and inform proposals)
and by the categorizer agent (as history/tag context for a hard decision).

All wrappers run the sync facade calls in a worker thread per convention and
return JSON-serializable dicts/lists.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.db import get_db


@tool
async def category_history(
    transaction_id: int | None = None,
    merchant_id: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Look up the category-change history (the audit log).

    Each event records the from/to category, the method (``llm`` / ``manual`` /
    ``taxonomy_migration``), the model, the agent's ``categorization_reasoning``
    (why a category was chosen), and the ``recategorization_reason`` (why a user
    changed it).

    Args:
        transaction_id: If given, return the full history of this one transaction
            (oldest first).
        merchant_id: If given (and transaction_id is not), return recent events
            for this merchant's transactions (newest first).
        limit: Max events to return when not scoped to a single transaction.
    """

    def _run() -> dict[str, Any]:
        db = get_db()
        if transaction_id is not None:
            events = db.events_for_transaction(transaction_id)
        elif merchant_id is not None:
            events = db.events_for_merchant(merchant_id, limit=limit)
        else:
            events = db.recent_category_events(limit=limit)
        return {"events": events, "count": len(events)}

    return await asyncio.to_thread(_run)


@tool
async def transaction_tags(transaction_ids: list[int]) -> dict[str, Any]:
    """Return the tag names applied to each of the given transactions.

    Args:
        transaction_ids: Transaction IDs to look up.
    """

    def _run() -> dict[str, Any]:
        mapping = get_db().tags_for_transactions(transaction_ids)
        # JSON object keys must be strings.
        return {"tags": {str(tid): names for tid, names in mapping.items()}}

    return await asyncio.to_thread(_run)


@tool
async def find_similar_tagged_transactions(
    tag_name: str, limit: int = 25
) -> dict[str, Any]:
    """Find recent transactions carrying a given tag.

    Useful as categorization context — e.g. a run of restaurant charges tagged
    "eurotrip" makes a new European-vendor charge more likely to be a restaurant.

    Args:
        tag_name: The tag to search for.
        limit: Max transactions to return (newest first).
    """

    def _run() -> dict[str, Any]:
        txns = get_db().get_transactions_by_tag(tag_name, limit=limit)
        return {"tag": tag_name, "transactions": txns, "count": len(txns)}

    return await asyncio.to_thread(_run)
