from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import Any

import loguru
from loguru import logger

from models.transaction import Transaction
from transactoid.infra.clients.plaid import PlaidClient, PlaidClientError
from transactoid.infra.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import get_category_id
from transactoid.tools.base import StandardTool
from transactoid.tools.categorize.categorizer_tool import (
    CategorizedTransaction,
    Categorizer,
)
from transactoid.tools.protocol import ToolInputSchema


@dataclass
class SyncResult:
    """Result from a single sync page."""

    categorized_added: list[CategorizedTransaction]
    categorized_modified: list[CategorizedTransaction]
    removed_transaction_ids: list[str]  # Plaid transaction IDs to delete
    next_cursor: str
    has_more: bool


@dataclass
class AccumulatedTransactions:
    """Accumulated transactions from all Plaid sync pages."""

    added: list[Transaction]
    modified: list[Transaction]
    removed: list[dict[str, Any]]
    final_cursor: str
    pages_fetched: int


@dataclass
class CategorizedBatch:
    """Results from categorizing accumulated transactions."""

    categorized_added: list[CategorizedTransaction]
    categorized_modified: list[CategorizedTransaction]


class SyncToolLogger:
    """Handles all logging for SyncTool with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance

    def fetch_start(self, cursor: str) -> None:
        """Log start of page fetch from Plaid."""
        cursor_label = cursor or "initial"
        self._logger.bind(cursor=cursor_label).info(
            "Fetching transactions from Plaid (cursor: {})", cursor_label
        )

    def fetch_complete(
        self, added_count: int, modified_count: int, removed_count: int, page_num: int
    ) -> None:
        """Log completion of page fetch."""
        self._logger.bind(
            added=added_count,
            modified=modified_count,
            removed=removed_count,
            page=page_num,
        ).info(
            "Plaid fetch complete: {} added, {} modified, {} removed (page {})",
            added_count,
            modified_count,
            removed_count,
            page_num,
        )

    def fetch_summary(
        self,
        total_added: int,
        total_modified: int,
        total_removed: int,
        total_pages: int,
    ) -> None:
        """Log summary of all fetched pages."""
        self._logger.bind(
            total_added=total_added,
            total_modified=total_modified,
            total_removed=total_removed,
            pages=total_pages,
        ).info(
            "Total fetched: {} added, {} modified, {} removed across {} pages",
            total_added,
            total_modified,
            total_removed,
            total_pages,
        )

    def mutation_retry(self, attempt: int, max_retries: int) -> None:
        """Log mutation error retry attempt."""
        self._logger.bind(attempt=attempt, max_retries=max_retries).warning(
            "Mutation detected, restarting fetch (attempt {}/{})",
            attempt,
            max_retries,
        )

    def categorization_start(
        self, total_count: int, added_count: int, modified_count: int
    ) -> None:
        """Log start of categorization phase."""
        self._logger.bind(
            total=total_count, added=added_count, modified=modified_count
        ).info(
            "Categorizing {} transactions ({} added, {} modified)",
            total_count,
            added_count,
            modified_count,
        )

    def persistence_start(self, transaction_count: int) -> None:
        """Log start of persistence phase."""
        self._logger.bind(count=transaction_count).info(
            "Persisting {} transactions to database", transaction_count
        )

    def deletion_start(self, deletion_count: int) -> None:
        """Log start of deletion phase."""
        self._logger.bind(count=deletion_count).info(
            "Deleting {} removed transactions", deletion_count
        )


class SyncTool:
    """
    Sync tool that calls Plaid's transaction sync API and categorizes all
    results using an LLM.
    """

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        db: DB,
        taxonomy: Taxonomy,
        *,
        access_token: str,
        cursor: str | None = None,
    ) -> None:
        """
        Initialize the sync tool.

        Args:
            plaid_client: Plaid client instance
            categorizer: Categorizer instance for LLM-based categorization
            db: Database instance for persisting transactions
            taxonomy: Taxonomy instance for transaction categorization
            access_token: Plaid access token for the item
            cursor: Optional cursor for incremental sync (None for initial sync)
        """
        self._plaid_client = plaid_client
        self._categorizer = categorizer
        self._db = db
        self._taxonomy = taxonomy
        self._access_token = access_token
        self._cursor = cursor
        self._logger = SyncToolLogger()

    def sync(
        self,
        *,
        count: int = 250,
    ) -> list[SyncResult]:
        """
        Sync all available transactions with automatic pagination.

        Handles pagination automatically, categorizes each page as it's fetched.

        Args:
            count: Maximum number of transactions per page (default: 250, max: 500)

        Returns:
            List of SyncResult objects, one per page processed

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        try:
            # Check if there's already an event loop running
            asyncio.get_running_loop()
            # If loop exists, run in a new thread to avoid conflict
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._sync_async(count=count))
                return future.result()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run()
            return asyncio.run(self._sync_async(count=count))

    async def _fetch_all_pages(self, *, count: int) -> AccumulatedTransactions:
        """
        Fetch all available transaction pages from Plaid.

        Handles pagination automatically with retry logic for
        TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION errors.

        Args:
            count: Maximum transactions per page (25-500)

        Returns:
            AccumulatedTransactions with all fetched data

        Raises:
            PlaidClientError: If max retries exceeded for mutation errors
        """
        current_cursor = self._cursor
        pagination_start_cursor = current_cursor

        added_all: list[Transaction] = []
        modified_all: list[Transaction] = []
        removed_all: list[dict[str, Any]] = []

        pages_fetched = 0
        max_retries = 3
        retry_count = 0

        while True:
            try:
                # Fetch page from Plaid
                self._logger.fetch_start(current_cursor or "")

                sync_result = self._plaid_client.sync_transactions(
                    self._access_token,
                    cursor=current_cursor,
                    count=count,
                )

                # Extract data
                added: list[Transaction] = sync_result.get("added", [])
                modified: list[Transaction] = sync_result.get("modified", [])
                removed: list[dict[str, Any]] = sync_result.get("removed", [])
                next_cursor: str = sync_result.get("next_cursor", "")
                has_more: bool = sync_result.get("has_more", False)

                # Accumulate
                added_all.extend(added)
                modified_all.extend(modified)
                removed_all.extend(removed)
                pages_fetched += 1

                # Progress logging
                self._logger.fetch_complete(
                    len(added), len(modified), len(removed), pages_fetched
                )

                # Check if done
                if not has_more:
                    self._logger.fetch_summary(
                        len(added_all),
                        len(modified_all),
                        len(removed_all),
                        pages_fetched,
                    )
                    break

                # Update cursor for next iteration
                current_cursor = next_cursor
                retry_count = 0

            except PlaidClientError as e:
                # Handle mutation during pagination
                error_msg = str(e)
                if "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in error_msg:
                    if retry_count < max_retries:
                        self._logger.mutation_retry(retry_count + 1, max_retries)
                        # Clear accumulators and restart
                        added_all = []
                        modified_all = []
                        removed_all = []
                        current_cursor = pagination_start_cursor
                        pages_fetched = 0
                        retry_count += 1
                        continue
                    else:
                        raise PlaidClientError(
                            f"Failed to sync after {max_retries} retries due to "
                            "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
                        ) from e
                else:
                    raise

        return AccumulatedTransactions(
            added=added_all,
            modified=modified_all,
            removed=removed_all,
            final_cursor=next_cursor,
            pages_fetched=pages_fetched,
        )

    async def _categorize_accumulated(
        self,
        accumulated: AccumulatedTransactions,
    ) -> CategorizedBatch:
        """
        Categorize all accumulated transactions using LLM.

        Processes added and modified transactions concurrently using
        the existing Categorizer with its semaphore limiting. Categorization
        is batched with 25 transactions per batch to manage LLM context size.

        Args:
            accumulated: All transactions from Plaid sync

        Returns:
            CategorizedBatch with categorized results
        """
        total_txns = len(accumulated.added) + len(accumulated.modified)
        self._logger.categorization_start(
            total_txns, len(accumulated.added), len(accumulated.modified)
        )

        # Categorize added and modified concurrently with batch_size=25
        categorized_added, categorized_modified = await asyncio.gather(
            self._categorizer.categorize(accumulated.added, batch_size=25),
            self._categorizer.categorize(accumulated.modified, batch_size=25),
        )

        return CategorizedBatch(
            categorized_added=categorized_added,
            categorized_modified=categorized_modified,
        )

    def _persist_all(
        self,
        categorized: CategorizedBatch,
        removed: list[dict[str, Any]],
    ) -> None:
        """
        Persist all categorized transactions to database.

        Args:
            categorized: All categorized transactions
            removed: Removed transaction data from Plaid
        """
        # Combine all categorized transactions
        all_categorized = (
            categorized.categorized_added + categorized.categorized_modified
        )

        # Extract removed transaction IDs
        removed_ids = [
            item.get("transaction_id", "")
            for item in removed
            if item.get("transaction_id")
        ]

        # Persist to database
        if all_categorized:
            self._logger.persistence_start(len(all_categorized))
            category_lookup = lambda key: get_category_id(self._db, self._taxonomy, key)
            self._db.save_transactions(category_lookup, all_categorized)

        if removed_ids:
            self._logger.deletion_start(len(removed_ids))
            self._db.delete_transactions_by_external_ids(removed_ids, source="PLAID")

    def _build_sync_result(
        self,
        categorized: CategorizedBatch,
        accumulated: AccumulatedTransactions,
    ) -> SyncResult:
        """Build SyncResult from categorized batch and accumulated data."""
        removed_ids = [
            item.get("transaction_id", "")
            for item in accumulated.removed
            if item.get("transaction_id")
        ]

        return SyncResult(
            categorized_added=categorized.categorized_added,
            categorized_modified=categorized.categorized_modified,
            removed_transaction_ids=removed_ids,
            next_cursor=accumulated.final_cursor,
            has_more=False,  # Always False after fetching all pages
        )

    async def _sync_async(
        self,
        *,
        count: int = 25,
    ) -> list[SyncResult]:
        """
        Three-phase sync: fetch all, categorize all, persist all.

        Phase 1: Fetch all pages from Plaid (fast, sequential)
        Phase 2: Categorize all transactions (slow, parallelized)
        Phase 3: Persist to database (fast, bulk operation)

        Args:
            count: Maximum number of transactions per page (default: 25, max: 500)

        Returns:
            List containing single SyncResult representing entire sync

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        # Phase 1: Fetch all transactions from Plaid
        accumulated = await self._fetch_all_pages(count=count)

        # Phase 2: Categorize all transactions concurrently
        categorized = await self._categorize_accumulated(accumulated)

        # Phase 3: Persist everything to database
        self._persist_all(categorized, accumulated.removed)

        # Return single SyncResult representing entire sync
        return [self._build_sync_result(categorized, accumulated)]


class SyncTransactionsTool(StandardTool):
    """
    Tool wrapper for syncing transactions via Plaid.

    Exposes the SyncTool functionality through the standardized Tool protocol
    for use across multiple frontends (CLI, ChatKit, MCP, etc.).
    """

    _name = "sync_transactions"
    _description = (
        "Trigger synchronization with Plaid to fetch latest transactions. "
        "Syncs all available transactions with automatic pagination, "
        "categorizes each page as it's fetched, and persists results to the database."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},  # No parameters needed - uses configured access token
        "required": [],
    }

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        db: DB,
        taxonomy: Taxonomy,
        access_token: str,
    ) -> None:
        """
        Initialize the sync transactions tool.

        Args:
            plaid_client: Plaid client instance
            categorizer: Categorizer instance for LLM-based categorization
            db: Database instance for persisting transactions
            taxonomy: Taxonomy instance for transaction categorization
            access_token: Plaid access token for the item
        """
        self._sync_tool = SyncTool(
            plaid_client=plaid_client,
            categorizer=categorizer,
            db=db,
            taxonomy=taxonomy,
            access_token=access_token,
            cursor=None,
        )

    def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute sync and return summary dict.

        Returns:
            JSON-serializable dict with sync results including:
            - status: "success" or "error"
            - pages_processed: Number of pages fetched
            - total_added: Total transactions added
            - total_modified: Total transactions modified
            - total_removed: Total transactions removed
        """
        try:
            results = self._sync_tool.sync()

            # Aggregate results into JSON-serializable dict
            total_added = sum(len(r.categorized_added) for r in results)
            total_modified = sum(len(r.categorized_modified) for r in results)
            total_removed = sum(len(r.removed_transaction_ids) for r in results)

            return {
                "status": "success",
                "pages_processed": len(results),
                "total_added": total_added,
                "total_modified": total_modified,
                "total_removed": total_removed,
            }
        except PlaidClientError as e:
            return {
                "status": "error",
                "error": f"Plaid sync failed: {e}",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Sync failed: {e}",
            }
