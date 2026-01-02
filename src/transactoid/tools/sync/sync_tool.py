from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import loguru
from loguru import logger

from models.transaction import Transaction
from transactoid.adapters.amazon import (
    AmazonItemsCSVLoader,
    AmazonOrdersCSVLoader,
    OrderAmountIndex,
    create_split_derived_transactions,
    is_amazon_transaction,
    preserve_enrichments_by_amount,
)
from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import get_category_id
from transactoid.tools.base import StandardTool
from transactoid.tools.categorize.categorizer_tool import (
    Categorizer,
)
from transactoid.tools.protocol import ToolInputSchema


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

    def plaid_persist_start(self, count: int) -> None:
        """Log start of Plaid persistence phase."""
        self._logger.bind(count=count).info(
            "Persisting {} transactions to plaid_transactions table", count
        )

    def mutation_start(self, count: int) -> None:
        """Log start of mutation phase."""
        self._logger.bind(count=count).info(
            "Creating derived transactions for {} Plaid transactions", count
        )

    def amazon_split(self, plaid_id: str, split_count: int) -> None:
        """Log Amazon transaction split."""
        self._logger.bind(plaid_id=plaid_id, splits=split_count).debug(
            "Split Amazon transaction {} into {} derived transactions",
            plaid_id,
            split_count,
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

    def _persist_to_plaid_table(
        self,
        accumulated: AccumulatedTransactions,
    ) -> list[int]:
        """
        Persist Plaid transactions to plaid_transactions table.

        Phase 2 of 5-phase sync workflow.

        Args:
            accumulated: All transactions from Plaid sync

        Returns:
            List of plaid_transaction_ids that were created/updated
        """
        all_txns = accumulated.added + accumulated.modified
        self._logger.plaid_persist_start(len(all_txns))

        plaid_ids: list[int] = []

        # Insert or update added/modified
        for txn in all_txns:
            # Parse date
            posted_at_str = txn.get("date", "")
            from datetime import datetime

            try:
                posted_at = datetime.strptime(posted_at_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            # Convert amount to cents
            amount = txn.get("amount", 0.0)
            amount_cents = int(amount * 100)

            plaid_txn = self._db.upsert_plaid_transaction(
                external_id=txn.get("transaction_id", ""),
                source="PLAID",
                account_id=txn.get("account_id", ""),
                posted_at=posted_at,
                amount_cents=amount_cents,
                currency=txn.get("iso_currency_code") or "USD",
                merchant_descriptor=txn.get("merchant_name") or txn.get("name"),
                institution=None,
            )
            plaid_ids.append(plaid_txn.plaid_transaction_id)

        # Delete removed
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

        return plaid_ids

    def _mutate_to_derived(
        self,
        plaid_ids: list[int],
        amazon_csv_dir: Path | None = None,
    ) -> list[int]:
        """
        Generate derived transactions from Plaid transactions.

        Phase 3 of 5-phase sync workflow. Applies mutations like Amazon
        splitting and preserves enrichments from old derived transactions.

        Args:
            plaid_ids: List of plaid_transaction_ids to process
            amazon_csv_dir: Directory containing Amazon CSV files (optional)

        Returns:
            List of derived transaction_ids that were created
        """
        self._logger.mutation_start(len(plaid_ids))

        derived_ids: list[int] = []
        csv_dir = amazon_csv_dir or Path(".transactions/amazon")

        # Load Amazon CSVs once for the entire batch
        orders_csv = csv_dir / "amazon-order-history-orders.csv"
        items_csv = csv_dir / "amazon-order-history-items.csv"
        amazon_orders = AmazonOrdersCSVLoader(orders_csv).load()
        amazon_items = AmazonItemsCSVLoader(items_csv).load()

        # Build amount index for O(1) order lookup
        order_index = OrderAmountIndex(amazon_orders)

        for plaid_id in plaid_ids:
            plaid_txn = self._db.get_plaid_transaction(plaid_id)
            if not plaid_txn:
                continue

            # Get existing derived transactions for preservation
            old_derived = self._db.get_derived_by_plaid_id(plaid_id)

            # Generate new derived transactions
            if is_amazon_transaction(plaid_txn.merchant_descriptor):
                new_derived_data = create_split_derived_transactions(
                    plaid_txn, order_index, amazon_items
                )
                if len(new_derived_data) > 1:
                    self._logger.amazon_split(
                        plaid_txn.external_id, len(new_derived_data)
                    )
            else:
                # 1:1 mapping for non-Amazon transactions
                new_derived_data = [
                    {
                        "plaid_transaction_id": plaid_txn.plaid_transaction_id,
                        "external_id": plaid_txn.external_id,
                        "amount_cents": plaid_txn.amount_cents,
                        "posted_at": plaid_txn.posted_at,
                        "merchant_descriptor": plaid_txn.merchant_descriptor,
                        "category_id": None,
                        "is_verified": False,
                    }
                ]

            # Preserve enrichments by amount matching
            if old_derived:
                new_derived_data = preserve_enrichments_by_amount(
                    old_derived, new_derived_data
                )
                # Delete old derived (CASCADE handles tags)
                self._db.delete_derived_by_plaid_id(plaid_id)

            # Insert new derived transactions
            for data in new_derived_data:
                derived_txn = self._db.insert_derived_transaction(data)
                derived_ids.append(derived_txn.transaction_id)

        return derived_ids

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

        self._logger.categorization_start(
            len(to_categorize), len(to_categorize), 0  # All are "added" from perspective
        )

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
        category_lookup = lambda key: get_category_id(self._db, self._taxonomy, key)
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
        """
        Pipelined sync: fetch → persist → mutate run concurrently, then batch categorize.

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

            txn_dicts.append({
                "external_id": txn.get("transaction_id", ""),
                "source": "PLAID",
                "account_id": txn.get("account_id", ""),
                "posted_at": posted_at,
                "amount_cents": amount_cents,
                "currency": txn.get("iso_currency_code") or "USD",
                "merchant_descriptor": txn.get("merchant_name") or txn.get("name"),
                "institution": None,
            })

        if not txn_dicts:
            return []

        return self._db.bulk_upsert_plaid_transactions(txn_dicts)

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
        """
        Create derived transactions for a batch of plaid_transaction_ids.

        Args:
            plaid_ids: List of plaid_transaction_ids to process

        Returns:
            List of derived transaction_ids that were created
        """
        derived_ids: list[int] = []
        csv_dir = Path(".transactions/amazon")

        # Load Amazon CSVs once for the entire batch
        orders_csv = csv_dir / "amazon-order-history-orders.csv"
        items_csv = csv_dir / "amazon-order-history-items.csv"
        amazon_orders = AmazonOrdersCSVLoader(orders_csv).load()
        amazon_items = AmazonItemsCSVLoader(items_csv).load()

        # Build amount index for O(1) order lookup
        order_index = OrderAmountIndex(amazon_orders)

        # Batch fetch all plaid transactions and old derived in 2 queries
        plaid_txns_map = self._db.get_plaid_transactions_by_ids(plaid_ids)
        old_derived_map = self._db.get_derived_by_plaid_ids(plaid_ids)

        for plaid_id in plaid_ids:
            plaid_txn = plaid_txns_map.get(plaid_id)
            if not plaid_txn:
                continue

            old_derived = old_derived_map.get(plaid_id, [])

            if is_amazon_transaction(plaid_txn.merchant_descriptor):
                new_derived_data = create_split_derived_transactions(
                    plaid_txn, order_index, amazon_items
                )
                if len(new_derived_data) > 1:
                    self._logger.amazon_split(
                        plaid_txn.external_id, len(new_derived_data)
                    )
            else:
                new_derived_data = [
                    {
                        "plaid_transaction_id": plaid_txn.plaid_transaction_id,
                        "external_id": plaid_txn.external_id,
                        "amount_cents": plaid_txn.amount_cents,
                        "posted_at": plaid_txn.posted_at,
                        "merchant_descriptor": plaid_txn.merchant_descriptor,
                        "category_id": None,
                        "is_verified": False,
                    }
                ]

            if old_derived:
                new_derived_data = preserve_enrichments_by_amount(
                    old_derived, new_derived_data
                )
                self._db.delete_derived_by_plaid_id(plaid_id)

            for data in new_derived_data:
                derived_txn = self._db.insert_derived_transaction(data)
                derived_ids.append(derived_txn.transaction_id)

        return derived_ids


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
