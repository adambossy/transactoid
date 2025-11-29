from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from models.transaction import Transaction
from tools.categorize.categorizer_tool import CategorizedTransaction


@dataclass
class SaveRowOutcome:
    external_id: str
    source: str  # "CSV" | "PLAID"
    action: str  # "inserted" | "updated" | "skipped-verified" | "skipped-duplicate"
    transaction_id: int | None = None
    reason: str | None = None


@dataclass
class SaveOutcome:
    inserted: int
    updated: int
    skipped_verified: int
    skipped_duplicate: int
    rows: list[SaveRowOutcome]


@dataclass
class ApplyTagsOutcome:
    applied: int
    created_tags: list[str]


class PersistTool:
    def __init__(self, db: "DB", taxonomy: "Taxonomy") -> None:
        self._db = db
        self._taxonomy = taxonomy

    def save_raw_transactions(
        self,
        txns: Iterable[Transaction],
        *,
        cursor: str,
    ) -> int:
        """
        Store raw transactions before categorization.

        This ensures transactions are persisted even if categorization fails.
        Transactions are stored with status 'pending_categorization' and can be
        retried later.

        Args:
            txns: Raw transactions to store
            cursor: Cursor associated with these transactions

        Returns:
            Number of transactions stored
        """
        # Minimal stub: store raw transactions for retry capability
        # In full implementation, this would insert transactions with
        # status='pending_categorization' and store the cursor
        count = sum(1 for _ in txns)
        return count

    def save_transactions(self, txns: Iterable[CategorizedTransaction]) -> SaveOutcome:
        # Minimal stub: no inserts/updates
        return SaveOutcome(
            inserted=0,
            updated=0,
            skipped_verified=0,
            skipped_duplicate=0,
            rows=[],
        )

    def bulk_recategorize_by_merchant(
        self,
        merchant_id: int,
        category_key: str,
        *,
        only_unverified: bool = True,
    ) -> int:
        # Minimal stub: no rows affected
        return 0

    def apply_tags(
        self, transaction_ids: list[int], tag_names: list[str]
    ) -> ApplyTagsOutcome:
        # Minimal stub: nothing applied, echo requested tags as created for visibility
        return ApplyTagsOutcome(applied=0, created_tags=list(tag_names))
