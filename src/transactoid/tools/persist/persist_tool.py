from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import get_category_id
from transactoid.tools.base import StandardTool
from transactoid.tools.protocol import ToolInputSchema


@dataclass
class ApplyTagsOutcome:
    applied: int
    created_tags: list[str]


class PersistTool:
    def __init__(self, db: DB, taxonomy: Taxonomy) -> None:
        self._db = db
        self._taxonomy = taxonomy

    def recategorize_merchant(
        self,
        merchant_id: int,
        category_key: str,
    ) -> int:
        """
        Recategorize all unverified transactions for a given merchant.

        Verified transactions are immutable and will never be changed.

        Args:
            merchant_id: ID of the merchant whose transactions will be updated.
            category_key: Taxonomy key for the new category.

        Returns:
            Number of transactions updated.

        Raises:
            ValueError: If the category_key is invalid.
        """
        if not self._taxonomy.is_valid_key(category_key):
            raise ValueError(f"Invalid category_key: {category_key!r}")

        category_id = get_category_id(self._db, self._taxonomy, category_key)
        if category_id is None:
            # Defensive guard; should not happen if is_valid_key is True but
            # keeps behavior explicit.
            raise ValueError(f"Category ID not found for key: {category_key!r}")

        return self._db.recategorize_merchant(merchant_id, category_id)

    def apply_tags(
        self, transaction_ids: list[int], tag_names: list[str]
    ) -> ApplyTagsOutcome:
        """
        Apply tags to transactions.

        Creates tags if they don't exist, then attaches them to the
        specified transactions. Skips duplicate tag-transaction relationships.

        Args:
            transaction_ids: List of transaction IDs to tag
            tag_names: List of tag names to apply (will be created if they don't exist)

        Returns:
            ApplyTagsOutcome with count of relationships created and list of
            newly created tags
        """
        if not transaction_ids or not tag_names:
            return ApplyTagsOutcome(applied=0, created_tags=[])

        # Deduplicate tag names while preserving order
        seen: set[str] = set()
        unique_tag_names: list[str] = []
        for tag_name in tag_names:
            if tag_name not in seen:
                seen.add(tag_name)
                unique_tag_names.append(tag_name)

        # Upsert all tags and collect their IDs
        tag_ids: list[int] = []
        created_tags: list[str] = []

        for tag_name in unique_tag_names:
            # Upsert tag (creates if new, updates if exists)
            tag = self._db.upsert_tag(tag_name)
            tag_ids.append(tag.tag_id)
            # Track as created (DB interface doesn't expose existence check,
            # so we conservatively assume all requested tags are new)
            created_tags.append(tag_name)

        # Attach tags to transactions
        # attach_tags returns count of new relationships created (skips duplicates)
        applied_count = self._db.attach_tags(transaction_ids, tag_ids)

        return ApplyTagsOutcome(applied=applied_count, created_tags=created_tags)


class RecategorizeTool(StandardTool):
    """
    Tool wrapper for recategorizing transactions by merchant.

    Exposes PersistTool.recategorize_merchant through the standardized
    Tool protocol.
    """

    _name = "recategorize_merchant"
    _description = (
        "Recategorize all unverified transactions for a given merchant. "
        "Verified transactions are immutable and will not be changed."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "merchant_id": {
                "type": "integer",
                "description": "ID of the merchant whose transactions will be updated",
            },
            "category_key": {
                "type": "string",
                "description": (
                    "Taxonomy key for the new category (e.g., 'FOOD.GROCERIES')"
                ),
            },
        },
        "required": ["merchant_id", "category_key"],
    }

    def __init__(self, persist_tool: PersistTool) -> None:
        """
        Initialize the recategorize tool.

        Args:
            persist_tool: PersistTool instance to delegate to
        """
        self._persist_tool = persist_tool

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute recategorization and return result.

        Args:
            merchant_id: ID of merchant
            category_key: New category key

        Returns:
            JSON-serializable dict with:
            - status: "success" or "error"
            - updated_count: Number of transactions updated
            - error: Error message if status is "error"
        """
        merchant_id: int = kwargs["merchant_id"]
        category_key: str = kwargs["category_key"]

        try:
            updated_count = self._persist_tool.recategorize_merchant(
                merchant_id, category_key
            )
            return {
                "status": "success",
                "updated_count": updated_count,
            }
        except ValueError as e:
            return {
                "status": "error",
                "error": str(e),
                "updated_count": 0,
            }


class TagTransactionsTool(StandardTool):
    """
    Tool wrapper for applying tags to transactions.

    Exposes PersistTool.apply_tags through the standardized Tool protocol.
    """

    _name = "tag_transactions"
    _description = "Apply user-defined tags to transactions."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "transaction_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of transaction IDs to tag",
            },
            "tag_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tag names to apply",
            },
        },
        "required": ["transaction_ids", "tag_names"],
    }

    def __init__(self, persist_tool: PersistTool) -> None:
        """
        Initialize the tag transactions tool.

        Args:
            persist_tool: PersistTool instance to delegate to
        """
        self._persist_tool = persist_tool

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute tagging and return result.

        Args:
            transaction_ids: List of transaction IDs
            tag_names: List of tag names

        Returns:
            JSON-serializable dict with:
            - status: "success"
            - applied: Number of tag-transaction relationships created
            - created_tags: List of newly created tag names
        """
        transaction_ids: list[int] = kwargs["transaction_ids"]
        tag_names: list[str] = kwargs["tag_names"]

        outcome = self._persist_tool.apply_tags(transaction_ids, tag_names)

        return {
            "status": "success",
            "applied": outcome.applied,
            "created_tags": outcome.created_tags,
        }
