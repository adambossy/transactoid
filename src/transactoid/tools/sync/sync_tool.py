from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import Any

import loguru
from loguru import logger

from models.transaction import Transaction
from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import get_category_id
from transactoid.tools.base import StandardTool
from transactoid.tools.categorize.categorizer_tool import (
    Categorizer,
)
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.sync.mutation_registry import MutationRegistry


@dataclass
class SyncResult:
    """Result from a single sync page."""

    removed_transaction_ids: list[str]  # Plaid transaction IDs to delete
    next_cursor: str
    has_more: bool
    added_count: int = 0
    modified_count: int = 0


@dataclass
class AccumulatedTransactions:
    """Accumulated transactions from all Plaid sync pages."""

    added: list[Transaction]
    modified: list[Transaction]
    removed: list[dict[str, Any]]
    final_cursor: str
    pages_fetched: int


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

    def deletion_start(self, deletion_count: int) -> None:
        """Log start of deletion phase."""
        self._logger.bind(count=deletion_count).info(
            "Deleting {} removed transactions", deletion_count
        )

    def pipeline_persist_start(self, batch_size: int, batch_num: int) -> None:
        """Log start of batch persistence in pipeline."""
        self._logger.bind(batch_size=batch_size, batch_num=batch_num).debug(
            "Persisting batch {} ({} transactions)...",
            batch_num,
            batch_size,
        )

    def pipeline_persist_complete(
        self,
        batch_size: int,
        plaid_ids_count: int,
        batch_num: int,
        elapsed_ms: int,
    ) -> None:
        """Log completion of batch persistence in pipeline."""
        self._logger.bind(
            batch_size=batch_size,
            plaid_ids=plaid_ids_count,
            batch_num=batch_num,
            elapsed_ms=elapsed_ms,
        ).debug(
            "Persisted batch {} ({} transactions → {} plaid_ids) in {}ms",
            batch_num,
            batch_size,
            plaid_ids_count,
            elapsed_ms,
        )

    def pipeline_mutate_start(self, plaid_ids_count: int, batch_num: int) -> None:
        """Log start of batch mutation in pipeline."""
        self._logger.bind(plaid_ids=plaid_ids_count, batch_num=batch_num).debug(
            "Mutating batch {} ({} plaid_ids)...",
            batch_num,
            plaid_ids_count,
        )

    def pipeline_mutate_complete(
        self,
        plaid_ids_count: int,
        derived_ids_count: int,
        batch_num: int,
        elapsed_ms: int,
    ) -> None:
        """Log completion of batch mutation in pipeline."""
        self._logger.bind(
            plaid_ids=plaid_ids_count,
            derived_ids=derived_ids_count,
            batch_num=batch_num,
            elapsed_ms=elapsed_ms,
        ).debug(
            "Mutated batch {} ({} plaid_ids → {} derived_ids) in {}ms",
            batch_num,
            plaid_ids_count,
            derived_ids_count,
            elapsed_ms,
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
        mutation_registry: MutationRegistry | None = None,
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
            mutation_registry: Optional registry for mutation plugins (e.g., Amazon)
        """
        self._plaid_client = plaid_client
        self._categorizer = categorizer
        self._db = db
        self._taxonomy = taxonomy
        self._access_token = access_token
        self._cursor = cursor
        self._logger = SyncToolLogger()
        self._mutation_registry = mutation_registry or MutationRegistry()

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

    async def _categorize_derived(
        self,
        derived_ids: list[int],
    ) -> None:
        """
        Categorize derived transactions using LLM.

        Phase 4 of 5-phase sync workflow. Only categorizes if category_id
        is NULL or is_verified is FALSE.

        Args:
            derived_ids: List of derived transaction IDs to categorize
        """
        derived_txns = self._db.get_derived_transactions_by_ids(derived_ids)

        # Filter to uncategorized or unverified
        to_categorize = [
            txn
            for txn in derived_txns
            if txn.category_id is None or not txn.is_verified
        ]

        if not to_categorize:
            return

        # All are "added" from perspective
        self._logger.categorization_start(len(to_categorize), len(to_categorize), 0)

        # Convert DerivedTransaction to dict format for categorizer
        txn_dicts = [
            {
                "transaction_id": txn.external_id,
                "date": txn.posted_at.isoformat(),
                "amount": txn.amount_cents / 100.0,
                "merchant_name": txn.merchant_descriptor,
                "name": txn.merchant_descriptor,
                "account_id": "",
                "iso_currency_code": "USD",
            }
            for txn in to_categorize
        ]

        # Categorize in batches
        categorized = await self._categorizer.categorize(txn_dicts, batch_size=25)

        # Build mapping from external_id to transaction_id
        external_to_id = {txn.external_id: txn.transaction_id for txn in to_categorize}

        # Update category_id for categorized transactions
        def category_lookup(key: str) -> int | None:
            return get_category_id(self._db, self._taxonomy, key)

        for cat_txn in categorized:
            external_id = cat_txn.txn.get("transaction_id", "")
            transaction_id = external_to_id.get(external_id)
            if transaction_id is None:
                continue

            # Determine category key (prefer revised if present)
            category_key = (
                cat_txn.revised_category_key
                if cat_txn.revised_category_key
                else cat_txn.category_key
            )
            category_id = category_lookup(category_key) if category_key else None

            if category_id:
                self._db.update_derived_category(transaction_id, category_id)

    def _build_sync_result_from_accumulated(
        self,
        accumulated: AccumulatedTransactions,
    ) -> SyncResult:
        """Build SyncResult from accumulated data (categorization persisted to DB)."""
        removed_ids = [
            item.get("transaction_id", "")
            for item in accumulated.removed
            if item.get("transaction_id")
        ]

        return SyncResult(
            removed_transaction_ids=removed_ids,
            next_cursor=accumulated.final_cursor,
            has_more=False,
            added_count=len(accumulated.added),
            modified_count=len(accumulated.modified),
        )

    async def _sync_async(
        self,
        *,
        count: int = 25,
    ) -> list[SyncResult]:
        """Pipelined sync: fetch, persist, mutate run concurrently.

        Pipeline stages (run concurrently):
        - fetch_producer: Fetches pages from Plaid, pushes to persist_queue
        - persist_consumer: Persists to plaid_transactions, pushes ids to mutate_queue
        - mutate_consumer: Creates derived_transactions, collects derived_ids

        Final stage (after pipeline):
        - Batch categorization of all derived transactions (for LLM efficiency)

        Args:
            count: Maximum number of transactions per page (default: 25, max: 500)

        Returns:
            List containing single SyncResult representing entire sync

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        max_retries = 3
        retry_count = 0
        pagination_start_cursor = self._cursor

        while retry_count <= max_retries:
            try:
                return await self._run_pipeline(count, pagination_start_cursor)
            except PlaidClientError as e:
                if "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        self._logger.mutation_retry(retry_count, max_retries)
                        continue
                raise

        raise PlaidClientError(
            f"Failed to sync after {max_retries} retries due to "
            "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
        )

    async def _run_pipeline(
        self,
        count: int,
        start_cursor: str | None,
    ) -> list[SyncResult]:
        """
        Run the pipelined fetch → persist → mutate workflow.

        Args:
            count: Max transactions per page
            start_cursor: Starting cursor for pagination

        Returns:
            List containing single SyncResult
        """
        # Queues for pipeline stages
        persist_queue: asyncio.Queue[list[Transaction] | None] = asyncio.Queue()
        mutate_queue: asyncio.Queue[list[int] | None] = asyncio.Queue()

        # Shared state for results
        accumulated = AccumulatedTransactions(
            added=[],
            modified=[],
            removed=[],
            final_cursor="",
            pages_fetched=0,
        )
        all_derived_ids: list[int] = []
        pipeline_error: list[Exception] = []  # Mutable container for error propagation

        async def fetch_producer() -> None:
            """Fetch pages from Plaid and push to persist_queue."""
            nonlocal accumulated
            current_cursor = start_cursor
            pages_fetched = 0

            try:
                while True:
                    self._logger.fetch_start(current_cursor or "")

                    sync_result = self._plaid_client.sync_transactions(
                        self._access_token,
                        cursor=current_cursor,
                        count=count,
                    )

                    added: list[Transaction] = sync_result.get("added", [])
                    modified: list[Transaction] = sync_result.get("modified", [])
                    removed: list[dict[str, Any]] = sync_result.get("removed", [])
                    next_cursor: str = sync_result.get("next_cursor", "")
                    has_more: bool = sync_result.get("has_more", False)

                    pages_fetched += 1
                    self._logger.fetch_complete(
                        len(added), len(modified), len(removed), pages_fetched
                    )

                    # Accumulate for result building
                    accumulated.added.extend(added)
                    accumulated.modified.extend(modified)
                    accumulated.removed.extend(removed)
                    accumulated.pages_fetched = pages_fetched
                    accumulated.final_cursor = next_cursor

                    # Push batch to persist queue
                    batch = added + modified
                    if batch:
                        await persist_queue.put(batch)

                    if not has_more:
                        self._logger.fetch_summary(
                            len(accumulated.added),
                            len(accumulated.modified),
                            len(accumulated.removed),
                            pages_fetched,
                        )
                        break

                    current_cursor = next_cursor

            except Exception as e:
                pipeline_error.append(e)
                raise
            finally:
                await persist_queue.put(None)  # Signal done

        async def persist_consumer() -> None:
            """Persist batches to plaid_transactions, push IDs to mutate_queue."""
            import time

            batch_num = 0
            try:
                while True:
                    batch = await persist_queue.get()
                    if batch is None:
                        break

                    if pipeline_error:
                        break  # Abort if fetch failed

                    batch_num += 1
                    self._logger.pipeline_persist_start(len(batch), batch_num)
                    start_time = time.monotonic()
                    plaid_ids = self._persist_batch_to_plaid(batch)
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    self._logger.pipeline_persist_complete(
                        len(batch),
                        len(plaid_ids),
                        batch_num,
                        elapsed_ms,
                    )
                    if plaid_ids:
                        await mutate_queue.put(plaid_ids)

            except Exception as e:
                pipeline_error.append(e)
                raise
            finally:
                await mutate_queue.put(None)  # Signal done

        async def mutate_consumer() -> None:
            """Consume from mutate_queue, create derived transactions."""
            import time

            nonlocal all_derived_ids
            batch_num = 0
            try:
                while True:
                    plaid_ids = await mutate_queue.get()
                    if plaid_ids is None:
                        break

                    if pipeline_error:
                        break  # Abort if upstream failed

                    batch_num += 1
                    self._logger.pipeline_mutate_start(len(plaid_ids), batch_num)
                    start_time = time.monotonic()
                    derived_ids = self._mutate_batch_to_derived(plaid_ids)
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    self._logger.pipeline_mutate_complete(
                        len(plaid_ids),
                        len(derived_ids),
                        batch_num,
                        elapsed_ms,
                    )
                    all_derived_ids.extend(derived_ids)

            except Exception as e:
                pipeline_error.append(e)
                raise

        # Run pipeline stages concurrently
        await asyncio.gather(
            fetch_producer(),
            persist_consumer(),
            mutate_consumer(),
        )

        # Re-raise any pipeline errors
        if pipeline_error:
            raise pipeline_error[0]

        # Handle removals
        if accumulated.removed:
            removed_ids = [
                item.get("transaction_id", "")
                for item in accumulated.removed
                if item.get("transaction_id")
            ]
            if removed_ids:
                self._logger.deletion_start(len(removed_ids))
                self._db.delete_plaid_transactions_by_external_ids(
                    removed_ids, source="PLAID"
                )

        # Batch categorization (after pipeline completes for LLM efficiency)
        if all_derived_ids:
            await self._categorize_derived(all_derived_ids)

        return [self._build_sync_result_from_accumulated(accumulated)]

    def _persist_batch_to_plaid(self, batch: list[Transaction]) -> list[int]:
        """
        Persist a batch of transactions to plaid_transactions table.

        Uses bulk upsert for performance (single DB round-trip instead of N).

        Args:
            batch: List of Plaid transactions to persist

        Returns:
            List of plaid_transaction_ids that were created/updated
        """
        from datetime import datetime

        # Transform batch into dicts for bulk upsert
        txn_dicts: list[dict[str, object]] = []
        for txn in batch:
            posted_at_str = txn.get("date", "")
            try:
                posted_at = datetime.strptime(posted_at_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            amount = txn.get("amount", 0.0)
            amount_cents = int(amount * 100)

            txn_dicts.append(
                {
                    "external_id": txn.get("transaction_id", ""),
                    "source": "PLAID",
                    "account_id": txn.get("account_id", ""),
                    "posted_at": posted_at,
                    "amount_cents": amount_cents,
                    "currency": txn.get("iso_currency_code") or "USD",
                    "merchant_descriptor": txn.get("merchant_name") or txn.get("name"),
                    "institution": None,
                }
            )

        if not txn_dicts:
            return []

        return self._db.bulk_upsert_plaid_transactions(txn_dicts)

    def _mutate_batch_to_derived(
        self,
        plaid_ids: list[int],
    ) -> list[int]:
        """
        Create derived transactions for a batch of plaid_transaction_ids.

        Uses the mutation registry to process transactions. Plugins like
        AmazonMutationPlugin can split transactions into multiple derived
        transactions. Default behavior is 1:1 mapping.

        Args:
            plaid_ids: List of plaid_transaction_ids to process

        Returns:
            List of derived transaction_ids that were created
        """
        # Batch fetch all plaid transactions and old derived in 2 queries
        plaid_txns_map = self._db.get_plaid_transactions_by_ids(plaid_ids)
        old_derived_map = self._db.get_derived_by_plaid_ids(plaid_ids)

        # Initialize plugins with full batch for O(N+M) matching efficiency
        plaid_txns_list = [
            plaid_txns_map[pid] for pid in plaid_ids if pid in plaid_txns_map
        ]
        self._mutation_registry.initialize_plugins(plaid_txns_list)

        # Collect all derived data and plaid_ids to delete
        all_new_derived_data: list[dict[str, Any]] = []
        plaid_ids_to_delete: list[int] = []

        for plaid_id in plaid_ids:
            plaid_txn = plaid_txns_map.get(plaid_id)
            if not plaid_txn:
                continue

            old_derived = old_derived_map.get(plaid_id, [])

            # Use registry to process (returns N derived for plugins, 1 for default)
            result = self._mutation_registry.process(plaid_txn, old_derived)
            all_new_derived_data.extend(result.derived_data_list)

            # Mark for deletion if there were old derived
            if old_derived:
                plaid_ids_to_delete.append(plaid_id)

        # Bulk delete old derived in single query
        if plaid_ids_to_delete:
            self._db.delete_derived_by_plaid_ids(plaid_ids_to_delete)

        # Bulk insert all new derived in single call
        return self._db.bulk_insert_derived_transactions(all_new_derived_data)


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
