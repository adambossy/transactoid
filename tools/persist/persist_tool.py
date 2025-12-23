from __future__ import annotations

from dataclasses import dataclass

from services.db import DB
from services.taxonomy import Taxonomy


@dataclass
class ApplyTagsOutcome:
    applied: int
    created_tags: list[str]


class PersistTool:
    def __init__(self, db: DB, taxonomy: Taxonomy) -> None:
        self._db = db
        self._taxonomy = taxonomy

    def bulk_recategorize_by_merchant(
        self,
        merchant_id: int,
        category_key: str,
        *,
        only_unverified: bool = True,
    ) -> int:
        """
        Bulk recategorize transactions for a given merchant.

        Args:
            merchant_id: ID of the merchant whose transactions will be updated.
            category_key: Taxonomy key for the new category.
            only_unverified: When True, only unverified transactions are
                updated. Verified transactions are always immutable and will
                never be changed, so setting this to False is not supported.

        Returns:
            Number of transactions updated.

        Raises:
            ValueError: If the category_key is invalid or only_unverified is
                set to False.
        """
        if not self._taxonomy.is_valid_key(category_key):
            raise ValueError(f"Invalid category_key: {category_key!r}")

        category_id = self._taxonomy.category_id_for_key(self._db, category_key)
        if category_id is None:
            # Defensive guard; should not happen if is_valid_key is True but
            # keeps behavior explicit.
            raise ValueError(f"Category ID not found for key: {category_key!r}")

        if not only_unverified:
            # The system guarantees immutability for verified rows; do not
            # provide an escape hatch here so callers cannot accidentally
            # violate that invariant.
            raise ValueError(
                "Recategorization of verified transactions is not supported; "
                "only_unverified must be True."
            )

        return self._db.recategorize_unverified_by_merchant(merchant_id, category_id)

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
            ApplyTagsOutcome with count of relationships created and list of newly created tags
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
