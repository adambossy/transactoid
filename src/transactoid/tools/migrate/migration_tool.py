from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from transactoid.adapters.cache.file_cache import FileCache
from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction as DBTransaction
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import get_category_id

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from transactoid.tools.categorize.categorizer_tool import (
        CategorizedTransaction,
        Categorizer,
    )

T = TypeVar("T")


def _run_async_safely(coro: Coroutine[object, object, T]) -> T:
    """
    Run an async coroutine from sync code, handling nested event loops.

    This handles the case where the calling code is already running in an
    async context (e.g., when called from an Agent SDK function tool).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)
    else:
        # Already in async context - run in a separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    operation: str
    success: bool
    affected_transaction_count: int = 0
    recategorized_count: int = 0
    verified_retained_count: int = 0
    verified_demoted_count: int = 0
    errors: list[str] = field(default_factory=list)
    summary: str = ""


class MigrationTool:
    """
    Orchestrates taxonomy migrations with transaction recategorization.

    Handles category operations (add, remove, rename, merge, split) while
    automatically recategorizing affected transactions and managing verified
    status based on confidence scores.
    """

    def __init__(
        self,
        db: DB,
        taxonomy: Taxonomy,
        categorizer: Categorizer,
        *,
        confidence_threshold: float = 0.70,
        file_cache: FileCache | None = None,
    ) -> None:
        self._db = db
        self._taxonomy = taxonomy
        self._categorizer = categorizer
        self._confidence_threshold = confidence_threshold
        self._file_cache = file_cache

    @property
    def taxonomy(self) -> Taxonomy:
        """Current taxonomy instance."""
        return self._taxonomy

    def add_category(
        self,
        key: str,
        name: str,
        parent_key: str | None,
        description: str | None = None,
    ) -> MigrationResult:
        """
        Add a new category to the taxonomy.

        Args:
            key: Unique key for the new category
            name: Display name for the category
            parent_key: Parent category key (None for root category)
            description: Optional category description

        Returns:
            MigrationResult with operation outcome
        """
        try:
            # Update taxonomy
            new_taxonomy = self._taxonomy.add_category(
                key, name, parent_key, description
            )

            # Sync to database
            self._db.replace_categories_from_taxonomy(new_taxonomy)

            # Update internal reference
            self._taxonomy = new_taxonomy

            return MigrationResult(
                operation="add",
                success=True,
                summary=f"Added category '{key}' under parent '{parent_key}'",
            )
        except ValueError as e:
            return MigrationResult(
                operation="add",
                success=False,
                errors=[str(e)],
                summary=f"Failed to add category: {e}",
            )

    def remove_category(
        self,
        key: str,
        fallback_key: str | None = None,
    ) -> MigrationResult:
        """
        Remove a category from the taxonomy.

        If the category has transactions, they must be reassigned to a fallback
        category before removal.

        Args:
            key: Key of category to remove
            fallback_key: Optional category key to reassign transactions to

        Returns:
            MigrationResult with operation outcome
        """
        try:
            # Check if category has transactions
            category_id = get_category_id(self._db, self._taxonomy, key)
            if category_id is None:
                return MigrationResult(
                    operation="remove",
                    success=False,
                    errors=[f"Category '{key}' not found in database"],
                    summary="Failed to remove category: not found",
                )

            transactions = self._db.get_transactions_by_category_id(category_id)
            affected_count = len(transactions)

            if affected_count > 0 and fallback_key is None:
                return MigrationResult(
                    operation="remove",
                    success=False,
                    errors=[
                        f"Category '{key}' has {affected_count} transactions. "
                        "Provide fallback_key to reassign them."
                    ],
                    summary="Failed: category has transactions without fallback",
                )

            # Reassign transactions if needed
            if affected_count > 0 and fallback_key is not None:
                fallback_id = get_category_id(self._db, self._taxonomy, fallback_key)
                if fallback_id is None:
                    return MigrationResult(
                        operation="remove",
                        success=False,
                        errors=[f"Fallback category '{fallback_key}' not found"],
                        summary="Failed: fallback category not found",
                    )

                txn_ids = [t.transaction_id for t in transactions]
                self._db.reassign_transactions_to_category(txn_ids, fallback_id)

            # Update taxonomy
            new_taxonomy = self._taxonomy.remove_category(key)

            # Sync to database
            self._db.replace_categories_from_taxonomy(new_taxonomy)

            # Update internal reference
            self._taxonomy = new_taxonomy

            # Clear cache
            self._clear_cache()

            summary = f"Removed category '{key}'"
            if affected_count > 0:
                summary += f", reassigned {affected_count} transactions"
                summary += f" to '{fallback_key}'"

            return MigrationResult(
                operation="remove",
                success=True,
                affected_transaction_count=affected_count,
                summary=summary,
            )
        except ValueError as e:
            return MigrationResult(
                operation="remove",
                success=False,
                errors=[str(e)],
                summary=f"Failed to remove category: {e}",
            )

    def rename_category(self, old_key: str, new_key: str) -> MigrationResult:
        """
        Rename a category key.

        No recategorization needed - just update the key in DB and taxonomy.

        Args:
            old_key: Current category key
            new_key: New category key

        Returns:
            MigrationResult with operation outcome
        """
        try:
            # Update taxonomy
            new_taxonomy = self._taxonomy.rename_category(old_key, new_key)

            # Update database
            self._db.update_category_key(old_key, new_key)

            # Update internal reference
            self._taxonomy = new_taxonomy

            # Clear cache
            self._clear_cache()

            return MigrationResult(
                operation="rename",
                success=True,
                summary=f"Renamed category '{old_key}' to '{new_key}'",
            )
        except ValueError as e:
            return MigrationResult(
                operation="rename",
                success=False,
                errors=[str(e)],
                summary=f"Failed to rename category: {e}",
            )

    def merge_categories(
        self,
        source_keys: list[str],
        target_key: str,
        *,
        recategorize: bool = False,
    ) -> MigrationResult:
        """
        Merge multiple categories into a target category.

        Args:
            source_keys: List of category keys to merge
            target_key: Target category key (must exist)
            recategorize: If True, run LLM recategorization on affected txns

        Returns:
            MigrationResult with operation outcome
        """
        try:
            # Get target category ID
            target_id = get_category_id(self._db, self._taxonomy, target_key)
            if target_id is None:
                return MigrationResult(
                    operation="merge",
                    success=False,
                    errors=[f"Target category '{target_key}' not found"],
                    summary="Failed: target category not found",
                )

            # Collect all affected transactions
            all_transactions: list[tuple[DBTransaction, bool]] = []
            for source_key in source_keys:
                source_id = get_category_id(self._db, self._taxonomy, source_key)
                if source_id is None:
                    return MigrationResult(
                        operation="merge",
                        success=False,
                        errors=[f"Source category '{source_key}' not found"],
                        summary=f"Failed: source '{source_key}' not found",
                    )
                txns = self._db.get_transactions_by_category_id(source_id)
                for txn in txns:
                    all_transactions.append((txn, txn.is_verified))

            affected_count = len(all_transactions)

            if recategorize and affected_count > 0:
                # Run recategorization with full taxonomy
                result = self._recategorize_with_threshold(all_transactions, target_key)
            else:
                # Simple reassignment without recategorization
                txn_ids = [t[0].transaction_id for t in all_transactions]
                self._db.reassign_transactions_to_category(txn_ids, target_id)
                result = MigrationResult(
                    operation="merge",
                    success=True,
                    affected_transaction_count=affected_count,
                    verified_retained_count=sum(
                        1 for _, was_verified in all_transactions if was_verified
                    ),
                )

            # Update taxonomy (remove source categories)
            new_taxonomy = self._taxonomy.merge_categories(source_keys, target_key)

            # Sync to database
            self._db.replace_categories_from_taxonomy(new_taxonomy)

            # Update internal reference
            self._taxonomy = new_taxonomy

            # Clear cache
            self._clear_cache()

            result.summary = (
                f"Merged {len(source_keys)} categories into '{target_key}', "
                f"affected {affected_count} transactions"
            )
            return result

        except ValueError as e:
            return MigrationResult(
                operation="merge",
                success=False,
                errors=[str(e)],
                summary=f"Failed to merge categories: {e}",
            )

    def split_category(
        self,
        source_key: str,
        targets: list[tuple[str, str, str | None]],
    ) -> MigrationResult:
        """
        Split a category into multiple new categories.

        All affected transactions will be recategorized using the LLM with
        only the target categories as options.

        Args:
            source_key: Key of category to split
            targets: List of (key, name, description) tuples for new categories

        Returns:
            MigrationResult with operation outcome
        """
        try:
            # Get source category ID and transactions
            source_id = get_category_id(self._db, self._taxonomy, source_key)
            if source_id is None:
                return MigrationResult(
                    operation="split",
                    success=False,
                    errors=[f"Source category '{source_key}' not found"],
                    summary="Failed: source category not found",
                )

            transactions = self._db.get_transactions_by_category_id(source_id)
            affected_count = len(transactions)
            all_transactions: list[tuple[DBTransaction, bool]] = [
                (txn, txn.is_verified) for txn in transactions
            ]

            # First, update taxonomy (add targets, remove source)
            new_taxonomy = self._taxonomy.split_category(source_key, targets)

            # Sync to database so new categories exist
            self._db.replace_categories_from_taxonomy(new_taxonomy)

            # Update internal reference
            self._taxonomy = new_taxonomy

            # Now recategorize using constrained taxonomy
            if affected_count > 0:
                target_keys = [t[0] for t in targets]
                result = self._recategorize_constrained_with_threshold(
                    all_transactions, target_keys
                )
                result.operation = "split"
            else:
                result = MigrationResult(
                    operation="split",
                    success=True,
                    affected_transaction_count=0,
                )

            # Clear cache
            self._clear_cache()

            result.summary = (
                f"Split '{source_key}' into {len(targets)} categories, "
                f"recategorized {result.recategorized_count} transactions"
            )
            return result

        except ValueError as e:
            return MigrationResult(
                operation="split",
                success=False,
                errors=[str(e)],
                summary=f"Failed to split category: {e}",
            )

    def _db_txn_to_categorizer_input(self, txn: DBTransaction) -> dict[str, object]:
        """Convert DB transaction to categorizer input format."""
        return {
            "transaction_id": str(txn.transaction_id),
            "account_id": txn.plaid_transaction.account_id,
            "amount": txn.amount_cents / 100.0,
            "iso_currency_code": txn.plaid_transaction.currency,
            "date": str(txn.posted_at),
            "name": txn.merchant_descriptor or "",
            "merchant_name": txn.merchant_descriptor,
            "pending": False,
            "payment_channel": None,
            "unofficial_currency_code": None,
            "category": None,
            "category_id": None,
            "personal_finance_category": None,
        }

    def _recategorize_with_threshold(
        self,
        transactions: list[tuple[DBTransaction, bool]],
        target_key: str,
    ) -> MigrationResult:
        """
        Recategorize transactions and apply confidence threshold.

        For verified transactions:
        - If new confidence >= threshold: keep verified
        - If new confidence < threshold: demote to unverified
        """
        from models.transaction import Transaction as TxnDict

        txn_dicts: list[TxnDict] = []
        for txn, _ in transactions:
            txn_dict = self._db_txn_to_categorizer_input(txn)
            txn_dicts.append(txn_dict)  # type: ignore[arg-type]

        # Run categorization (handles both sync and async calling contexts)
        categorized = _run_async_safely(self._categorizer.categorize(txn_dicts))

        return self._apply_categorization_results(transactions, categorized, target_key)

    def _recategorize_constrained_with_threshold(
        self,
        transactions: list[tuple[DBTransaction, bool]],
        allowed_keys: list[str],
    ) -> MigrationResult:
        """
        Recategorize transactions with constrained taxonomy.
        """
        from models.transaction import Transaction as TxnDict

        txn_dicts: list[TxnDict] = []
        for txn, _ in transactions:
            txn_dict = self._db_txn_to_categorizer_input(txn)
            txn_dicts.append(txn_dict)  # type: ignore[arg-type]

        # Run constrained categorization (handles both sync and async calling contexts)
        categorized = _run_async_safely(
            self._categorizer.categorize_constrained(txn_dicts, allowed_keys)
        )

        return self._apply_categorization_results(transactions, categorized, None)

    def _apply_categorization_results(
        self,
        transactions: list[tuple[DBTransaction, bool]],
        categorized: list[CategorizedTransaction],
        default_key: str | None,
    ) -> MigrationResult:
        """Apply categorization results with confidence threshold logic."""
        verified_retained = 0
        verified_demoted = 0
        recategorized = 0

        for (txn, was_verified), cat_result in zip(transactions, categorized):
            # Get final category and confidence
            final_key = cat_result.revised_category_key or cat_result.category_key
            final_confidence = (
                cat_result.revised_category_confidence
                if cat_result.revised_category_confidence is not None
                else cat_result.category_confidence
            )

            # Get category ID
            category_id = get_category_id(self._db, self._taxonomy, final_key)
            if category_id is None and default_key:
                category_id = get_category_id(self._db, self._taxonomy, default_key)

            if category_id is None:
                continue

            # Determine verified status
            if was_verified:
                if final_confidence >= self._confidence_threshold:
                    # Keep verified
                    self._db.reassign_transactions_to_category(
                        [txn.transaction_id], category_id, reset_verified=False
                    )
                    verified_retained += 1
                else:
                    # Demote to unverified
                    self._db.reassign_transactions_to_category(
                        [txn.transaction_id], category_id, reset_verified=True
                    )
                    verified_demoted += 1
            else:
                # Unverified stays unverified
                self._db.reassign_transactions_to_category(
                    [txn.transaction_id], category_id, reset_verified=False
                )

            recategorized += 1

        return MigrationResult(
            operation="recategorize",
            success=True,
            affected_transaction_count=len(transactions),
            recategorized_count=recategorized,
            verified_retained_count=verified_retained,
            verified_demoted_count=verified_demoted,
        )

    def _clear_cache(self) -> None:
        """Clear the categorization cache after taxonomy changes."""
        if self._file_cache is not None:
            self._file_cache.clear_namespace("categorize")
