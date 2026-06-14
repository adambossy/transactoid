"""Tools for the per-transaction categorizer agent.

The categorizer agent gets a small, read-only-plus-one-writer toolset:

- history / tags / events read tools (shared with the chat agent, defined in
  ``penny.tools.audit`` and ``penny.tools.categorizer_reads``),
- ``web_search`` — provided natively by the model provider (not defined here),
- ``submit_categorization`` — the FINAL tool. It persists the decision (category
  + ``categorization_reasoning`` audit) and ends the loop. Its arguments are the
  decision of record; the agent's trailing assistant message is ignored.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import StaticToolset, tool
from agent_harness.core.toolsets import Toolset

from penny.db import get_db
from penny.services import get_taxonomy
from penny.taxonomy.loader import get_category_id
from penny.tools.audit import (
    category_history,
    find_similar_tagged_transactions,
    transaction_tags,
)


@tool
async def merchant_category_history(descriptor: str) -> dict[str, Any]:
    """How an exact merchant descriptor has been categorized before.

    Returns the distribution of categories previously assigned to this descriptor
    (with verified counts) plus recent transactions — strong signal for an
    ambiguous merchant.

    Args:
        descriptor: The exact merchant descriptor string to look up.
    """

    def _run() -> dict[str, Any]:
        db = get_db()
        return {
            "descriptor": descriptor,
            "distribution": db.get_merchant_category_distribution(descriptor),
            "recent": db.get_transactions_by_merchant_descriptor(descriptor, limit=10),
        }

    return await asyncio.to_thread(_run)


@tool
async def submit_categorization(
    transaction_id: int,
    category_key: str,
    confidence: float,
    reasoning: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Record the final categorization decision for a transaction. Call this LAST.

    This persists the chosen category and writes ``reasoning`` (plus any
    ``evidence``) to the audit log as ``categorization_reasoning`` so the decision
    can be debugged later. After calling this you are done — your final text reply
    is ignored.

    Args:
        transaction_id: The transaction being categorized (given to you in the prompt).
        category_key: The chosen taxonomy key (e.g. ``food_and_dining.groceries``).
            Must be a valid key in the live taxonomy.
        confidence: Your confidence in this category, 0.0–1.0.
        reasoning: A concise explanation of WHY this category — the audit trail.
        evidence: Optional short bullets of what you consulted (history, tags,
            web_search findings) that informed the decision.
    """

    def _run() -> dict[str, Any]:
        db = get_db()
        taxonomy = get_taxonomy()
        if not taxonomy.is_valid_key(category_key):
            return {
                "status": "error",
                "message": f"Invalid category key: {category_key}",
            }
        category_id = get_category_id(db, taxonomy, category_key)
        if category_id is None:
            return {
                "status": "error",
                "message": f"Category ID not found for key: {category_key}",
            }
        audit = reasoning
        if evidence:
            audit = (
                reasoning + "\n\nEvidence:\n" + "\n".join(f"- {e}" for e in evidence)
            )
        try:
            # method='llm' routes ``category_reason`` to categorization_reasoning.
            db.update_derived_mutable(
                transaction_id,
                {
                    "category_id": category_id,
                    "category_method": "llm",
                    "category_reason": audit,
                },
            )
            return {
                "status": "success",
                "transaction_id": transaction_id,
                "category_key": category_key,
                "confidence": confidence,
            }
        except Exception as exc:  # noqa: BLE001 - surface to the agent as tool output
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)


def build_categorizer_toolset() -> Toolset:
    """The categorizer agent's toolset (read tools + final submit tool).

    ``web_search`` is provided natively by the model provider and is not listed
    here. No filesystem / bash / skills tools are granted (capability confinement).
    """
    return StaticToolset(
        name="categorizer",
        tools=[
            category_history,
            transaction_tags,
            find_similar_tagged_transactions,
            merchant_category_history,
            submit_categorization,
        ],
    )
