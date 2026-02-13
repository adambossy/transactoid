from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import loguru
from loguru import logger

from models.transaction import Transaction
from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.tools.base import StandardTool
from transactoid.tools.categorize.categorizer_tool import (
    Categorizer,
)
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.sync.investment_classification import (
    investment_activity_reporting_mode,
)
from transactoid.tools.sync.mutation_registry import MutationRegistry

if TYPE_CHECKING:
    from transactoid.adapters.db.models import DerivedTransaction, PlaidItem


@dataclass
class SyncResult:
    """Result from syncing a single Plaid item."""

    removed_transaction_ids: list[str]  # Plaid transaction IDs to delete
    next_cursor: str
    has_more: bool
    added_count: int = 0
    modified_count: int = 0


@dataclass
class SyncSummary:
    """Aggregated results from syncing all Plaid items."""

    total_added: int
    total_modified: int
    total_removed: int
    items_synced: int
    investment_added: int = 0
    investment_skipped_excluded: int = 0
    consent_required_items: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {
            "total_added": self.total_added,
            "total_modified": self.total_modified,
            "total_removed": self.total_removed,
            "items_synced": self.items_synced,
            "investment_added": self.investment_added,
            "investment_skipped_excluded": self.investment_skipped_excluded,
        }
        if self.consent_required_items:
            result["consent_required_items"] = self.consent_required_items
        return result


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

    Syncs ALL connected Plaid items automatically, handling cursor persistence
    and mutation registry setup internally.
    """

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer_factory: Callable[[], Categorizer],
        db: DB,
        taxonomy: Taxonomy,
    ) -> None:
        """
        Initialize the sync tool.

        Args:
            plaid_client: Plaid client instance
            categorizer_factory: Factory callable that creates a Categorizer on demand.
                Defers OpenAI client init, promptorium scan, and merchant rule loading
                until categorization is actually needed.
            db: Database instance for persisting transactions
            taxonomy: Taxonomy instance for transaction categorization
        """
        self._plaid_client = plaid_client
        self._categorizer_factory = categorizer_factory
        self._categorizer: Categorizer | None = None
        self._db = db
        self._taxonomy = taxonomy
        self._logger = SyncToolLogger()

        # Register Amazon mutation plugin; it reads scraped orders from DB tables.
        self._mutation_registry = MutationRegistry()
        from transactoid.adapters.amazon import (
            AmazonMutationPlugin,
            AmazonMutationPluginConfig,
        )

        self._mutation_registry.register(
            AmazonMutationPlugin(db, AmazonMutationPluginConfig())
        )

    async def sync(
        self,
        *,
        count: int = 250,
    ) -> SyncSummary:
        """
        Sync ALL connected Plaid items with automatic pagination.

        Items are synced in parallel for maximum performance. Each item has its
        own independent cursor, so there are no cross-item dependencies.

        For each Plaid item:
        - Loads cursor from database for incremental sync
        - Fetches transactions from Plaid with pagination
        - Persists and categorizes transactions
        - Saves cursor after successful sync

        Args:
            count: Maximum number of transactions per page (default: 250, max: 500)

        Returns:
            SyncSummary with aggregated results across all items

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        plaid_items = self._db.list_plaid_items()
        if not plaid_items:
            return SyncSummary(
                total_added=0, total_modified=0, total_removed=0, items_synced=0
            )

        # Sync all items in parallel (each has independent cursor)
        tasks = [self._sync_item_with_cursor(item, count) for item in plaid_items]
        all_results_with_investments = await asyncio.gather(*tasks)

        # Flatten results and aggregate investments
        all_results: list[SyncResult] = []
        total_inv_added = 0
        total_inv_excluded = 0
        consent_errors: list[str] = []

        for (
            results,
            inv_added,
            inv_excluded,
            consent_error,
        ) in all_results_with_investments:
            all_results.extend(results)
            total_inv_added += inv_added
            total_inv_excluded += inv_excluded
            if consent_error:
                consent_errors.append(consent_error)

        summary = self._aggregate_results(all_results, len(plaid_items))
        summary.investment_added = total_inv_added
        summary.investment_skipped_excluded = total_inv_excluded
        if consent_errors:
            summary.consent_required_items = consent_errors

        return summary

    async def _sync_item_with_cursor(
        self,
        item: PlaidItem,
        count: int,
    ) -> tuple[list[SyncResult], int, int, str | None]:
        """
        Sync a single Plaid item with cursor management.

        Loads cursor, syncs item, saves cursor atomically per item.
        Safe to run in parallel with other items.

        Args:
            item: PlaidItem with access_token and item_id
            count: Maximum number of transactions per page

        Returns:
            Tuple of (sync_results, investment_added, investment_excluded,
            consent_error)
        """
        cursor = self._db.get_sync_cursor(item.item_id)
        results = await self._sync_item_async(
            item.access_token, item.item_id, cursor, count
        )

        # Persist cursor after successful sync
        if results:
            self._db.set_sync_cursor(item.item_id, results[-1].next_cursor)

        # Sync investments for this item (parallel operation)
        inv_added, inv_excluded, consent_error = await self._sync_investments_for_item(
            item
        )

        return (results, inv_added, inv_excluded, consent_error)

    def _aggregate_results(
        self, results: list[SyncResult], items_synced: int
    ) -> SyncSummary:
        """Aggregate results from all items into a summary."""
        return SyncSummary(
            total_added=sum(r.added_count for r in results),
            total_modified=sum(r.modified_count for r in results),
            total_removed=sum(len(r.removed_transaction_ids) for r in results),
            items_synced=items_synced,
        )

    async def _sync_investments_for_item(
        self,
        item: PlaidItem,
    ) -> tuple[int, int, str | None]:
        """Sync investment transactions for a single item.

        Uses watermark-based incremental sync with pagination:
        - Initial run: backfill 730 days
        - Incremental: fetch from watermark minus 7-day overlap
        - Paginated: loops through all pages until all transactions fetched
        - Dedupe by (external_id, source) handles overlaps

        Args:
            item: PlaidItem with access_token and item_id

        Returns:
            Tuple of (added_count, excluded_count, consent_error_message)
            consent_error_message is set if ADDITIONAL_CONSENT_REQUIRED
        """
        from datetime import date, timedelta

        # Determine start date based on watermark
        if item.investments_synced_through:
            # Incremental: use watermark with 7-day overlap for safety
            start_date = item.investments_synced_through - timedelta(days=7)
        else:
            # Initial backfill: 730 days
            start_date = date.today() - timedelta(days=730)

        end_date = date.today()

        try:
            # Paginated fetch: loop through all pages
            all_investment_txns: list[dict[str, Any]] = []
            all_securities: dict[str, dict[str, Any]] = {}
            offset = 0
            page_count = 0

            while True:
                page_count += 1
                self._logger._logger.debug(
                    "Fetching investment transactions page {} (offset={}, count=500)",
                    page_count,
                    offset,
                )

                # Fetch one page of investment transactions from Plaid
                result = await asyncio.to_thread(
                    self._plaid_client.get_investment_transactions,
                    item.access_token,
                    start_date=start_date,
                    end_date=end_date,
                    count=500,
                    offset=offset,
                )

                investment_txns = result.get("investment_transactions", [])
                total_count = result.get("total_investment_transactions", 0)

                # Merge securities (dedupe by security_id)
                securities = result.get("securities", [])
                for sec in securities:
                    all_securities[sec["security_id"]] = sec

                all_investment_txns.extend(investment_txns)
                self._logger._logger.debug(
                    "Page {} fetched: {} transactions (total so far: {})",
                    page_count,
                    len(investment_txns),
                    len(all_investment_txns),
                )

                # Check if we've fetched all pages
                if not investment_txns or len(all_investment_txns) >= total_count:
                    self._logger._logger.info(
                        "Investment sync complete: {} transactions across {} pages",
                        len(all_investment_txns),
                        page_count,
                    )
                    break

                offset += 500

            investment_txns = all_investment_txns
            securities_map = all_securities

            if not investment_txns:
                # No transactions but no error - update watermark and continue
                self._db.set_investments_watermark(item.item_id, end_date)
                return (0, 0, None)

            # Normalize and persist investment transactions
            added_count = 0
            excluded_count = 0

            for inv_txn in investment_txns:
                # Normalize to plaid_transactions format
                txn_dict = self._normalize_investment_transaction(
                    inv_txn, securities_map, item.item_id
                )

                # Persist to plaid_transactions with source=PLAID_INVESTMENT
                plaid_ids = self._db.bulk_upsert_plaid_transactions([txn_dict])

                if not plaid_ids:
                    continue

                # Create derived transaction with reporting_mode
                reporting_mode = investment_activity_reporting_mode(
                    transaction_type=inv_txn.get("type"),
                    transaction_subtype=inv_txn.get("subtype"),
                    transaction_name=inv_txn.get("name", ""),
                )

                derived_data = {
                    "plaid_transaction_id": plaid_ids[0],
                    "external_id": inv_txn["investment_transaction_id"],
                    "amount_cents": txn_dict["amount_cents"],
                    "posted_at": txn_dict["posted_at"],
                    "merchant_descriptor": txn_dict["merchant_descriptor"],
                    "reporting_mode": reporting_mode,
                }

                # Check if derived already exists
                existing_derived = self._db.get_derived_by_plaid_ids([plaid_ids[0]])
                if existing_derived.get(plaid_ids[0]):
                    # Update existing derived with reporting_mode
                    txn_id = existing_derived[plaid_ids[0]][0].transaction_id
                    self._db.bulk_update_derived_reporting_mode(
                        {txn_id: reporting_mode}
                    )
                else:
                    # Insert new derived
                    self._db.bulk_insert_derived_transactions([derived_data])

                if reporting_mode == "DEFAULT_EXCLUDE":
                    excluded_count += 1
                else:
                    added_count += 1

            # Update watermark after successful sync
            self._db.set_investments_watermark(item.item_id, end_date)

            return (added_count, excluded_count, None)

        except PlaidClientError as e:
            error_str = str(e)
            if "ADDITIONAL_CONSENT_REQUIRED" in error_str:
                # Non-fatal: return consent error message
                return (
                    0,
                    0,
                    f"Investments consent required for item {item.item_id[:8]}...",
                )
            # Other Plaid errors should not fail the whole sync
            self._logger._logger.warning(
                "Failed to sync investments for item {}: {}", item.item_id, e
            )
            return (0, 0, None)

    def _normalize_investment_transaction(
        self,
        inv_txn: dict[str, Any],
        securities_map: dict[str, dict[str, Any]],
        item_id: str,
    ) -> dict[str, object]:
        """Normalize investment transaction to plaid_transactions format.

        Args:
            inv_txn: Investment transaction dict from Plaid
            securities_map: Map of security_id to security details
            item_id: Plaid item ID

        Returns:
            Dict formatted for plaid_transactions table with source=PLAID_INVESTMENT
        """
        from datetime import datetime

        # Use investment_transaction_id as external_id
        external_id = inv_txn["investment_transaction_id"]

        # Parse date
        posted_at_str = inv_txn.get("date", "")
        try:
            posted_at = datetime.strptime(posted_at_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            posted_at = datetime.today().date()

        # Amount in cents
        amount = inv_txn.get("amount", 0.0)
        amount_cents = int(amount * 100)

        # Merchant descriptor: use name, fallback to security name
        merchant_descriptor = inv_txn.get("name", "")
        if not merchant_descriptor and inv_txn.get("security_id"):
            security = securities_map.get(inv_txn["security_id"])
            if security:
                merchant_descriptor = security.get("name", "")

        return {
            "external_id": external_id,
            "source": "PLAID_INVESTMENT",
            "account_id": inv_txn["account_id"],
            "item_id": item_id,
            "posted_at": posted_at,
            "amount_cents": amount_cents,
            "currency": inv_txn.get("iso_currency_code") or "USD",
            "merchant_descriptor": merchant_descriptor,
            "institution": None,
        }

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

        # Lazily initialize categorizer on first use
        if self._categorizer is None:
            self._categorizer = self._categorizer_factory()

        # Categorize in batches
        categorized = await self._categorizer.categorize(txn_dicts, batch_size=25)

        # Build mapping from external_id to transaction_id
        external_to_id = {txn.external_id: txn.transaction_id for txn in to_categorize}

        # Collect unique category keys and resolve them in one bulk query
        unique_keys: set[str] = set()
        for cat_txn in categorized:
            key = (
                cat_txn.revised_category_key
                if cat_txn.revised_category_key
                else cat_txn.category_key
            )
            if key:
                unique_keys.add(key)

        category_id_map = self._db.get_category_ids_by_keys(list(unique_keys))

        # Collect all category updates for bulk operation
        category_updates: dict[int, int] = {}

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
            category_id = category_id_map.get(category_key) if category_key else None

            if category_id:
                category_updates[transaction_id] = category_id

        # Bulk update all categories in single DB transaction
        if category_updates:
            self._db.bulk_update_derived_categories(
                category_updates,
                method="llm",
                model=self._categorizer.model_name,
                reason="sync_categorize",
            )

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

    async def _sync_item_async(
        self,
        access_token: str,
        item_id: str,
        cursor: str | None,
        count: int,
    ) -> list[SyncResult]:
        """Pipelined sync: fetch, persist, mutate run concurrently.

        Pipeline stages (run concurrently):
        - fetch_producer: Fetches pages from Plaid, pushes to persist_queue
        - persist_consumer: Persists to plaid_transactions, pushes ids to mutate_queue
        - mutate_consumer: Creates derived_transactions, collects derived_ids

        Final stage (after pipeline):
        - Batch categorization of all derived transactions (for LLM efficiency)

        Args:
            access_token: Plaid access token for the item
            item_id: Plaid item ID for FK relationship
            cursor: Optional cursor for incremental sync
            count: Maximum number of transactions per page

        Returns:
            List containing single SyncResult representing entire sync

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        max_retries = 3
        retry_count = 0

        while retry_count <= max_retries:
            try:
                return await self._run_pipeline(access_token, item_id, cursor, count)
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
        access_token: str,
        item_id: str,
        start_cursor: str | None,
        count: int,
    ) -> list[SyncResult]:
        """
        Run the pipelined fetch → persist → mutate workflow.

        Args:
            access_token: Plaid access token for the item
            item_id: Plaid item ID for FK relationship
            start_cursor: Starting cursor for pagination
            count: Max transactions per page

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

            # Get excluded account_id for "CORP Account - JOIA"
            excluded_account_id = await asyncio.to_thread(
                self._get_excluded_account_id, access_token
            )
            if excluded_account_id:
                self._logger._logger.debug(
                    "Filtering transactions from account: {}", excluded_account_id
                )

            try:
                while True:
                    self._logger.fetch_start(current_cursor or "")

                    # Run sync Plaid call in thread pool to avoid blocking event loop
                    sync_result = await asyncio.to_thread(
                        self._plaid_client.sync_transactions,
                        access_token,
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

                    # Filter out excluded account if needed
                    if excluded_account_id:
                        added = [
                            t
                            for t in added
                            if t.get("account_id") != excluded_account_id
                        ]
                        modified = [
                            t
                            for t in modified
                            if t.get("account_id") != excluded_account_id
                        ]
                        removed = [
                            t
                            for t in removed
                            if t.get("account_id") != excluded_account_id
                        ]

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
                    plaid_ids = self._persist_batch_to_plaid(batch, item_id)
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

    def _persist_batch_to_plaid(
        self, batch: list[Transaction], item_id: str
    ) -> list[int]:
        """
        Persist a batch of transactions to plaid_transactions table.

        Uses bulk upsert for performance (single DB round-trip instead of N).

        Args:
            batch: List of Plaid transactions to persist
            item_id: Plaid item ID for FK relationship

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
                    "item_id": item_id,
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
        unchanged_derived_ids: list[int] = []

        for plaid_id in plaid_ids:
            plaid_txn = plaid_txns_map.get(plaid_id)
            if not plaid_txn:
                continue

            old_derived = old_derived_map.get(plaid_id, [])

            # Use registry to process (returns N derived for plugins, 1 for default)
            result = self._mutation_registry.process(plaid_txn, old_derived)

            # Skip delete+reinsert when derived data is unchanged (1:1 only)
            if (
                old_derived
                and len(old_derived) == 1
                and len(result.derived_data_list) == 1
                and self._derived_unchanged(old_derived[0], result.derived_data_list[0])
            ):
                unchanged_derived_ids.append(old_derived[0].transaction_id)
                continue

            all_new_derived_data.extend(result.derived_data_list)

            # Mark for deletion if there were old derived
            if old_derived:
                plaid_ids_to_delete.append(plaid_id)

        # Bulk delete old derived in single query
        if plaid_ids_to_delete:
            self._db.delete_derived_by_plaid_ids(plaid_ids_to_delete)

        # Bulk insert all new derived in single call
        new_ids = self._db.bulk_insert_derived_transactions(all_new_derived_data)
        return unchanged_derived_ids + new_ids

    @staticmethod
    def _derived_unchanged(
        old: DerivedTransaction,
        new_data: dict[str, Any],
    ) -> bool:
        """Check if derived transaction data is unchanged.

        Compares the core fields that come from Plaid (amount, date,
        merchant descriptor). If all match, the mutation can be skipped.
        """
        return (
            old.amount_cents == new_data.get("amount_cents")
            and old.posted_at == new_data.get("posted_at")
            and old.merchant_descriptor == new_data.get("merchant_descriptor")
        )

    def _get_excluded_account_id(self, access_token: str) -> str | None:
        """Get account_id for 'CORP Account - JOIA' if it exists.

        Args:
            access_token: Plaid access token for the item

        Returns:
            Account ID if found, None otherwise
        """
        try:
            accounts = self._plaid_client.get_accounts(access_token)
            for account in accounts:
                if account.get("name") == "CORP Account - JOIA":
                    return account["account_id"]
        except Exception as e:
            # If we can't fetch accounts, don't filter (fail open)
            self._logger._logger.debug("Failed to fetch accounts for filtering: {}", e)
        return None


class SyncTransactionsTool(StandardTool):
    """
    Tool wrapper for syncing transactions via Plaid.

    Exposes the SyncTool functionality through the standardized Tool protocol
    for use across multiple frontends (CLI, ChatKit, MCP, etc.).
    """

    _name = "sync_transactions"
    _description = (
        "Trigger synchronization with Plaid to fetch latest transactions. "
        "Syncs ALL connected Plaid items with automatic pagination, "
        "categorizes transactions, and persists results to the database."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},  # No parameters needed - syncs all items automatically
        "required": [],
    }

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer_factory: Callable[[], Categorizer],
        db: DB,
        taxonomy: Taxonomy,
    ) -> None:
        """
        Initialize the sync transactions tool.

        Args:
            plaid_client: Plaid client instance
            categorizer_factory: Factory callable that creates a Categorizer on demand
            db: Database instance for persisting transactions
            taxonomy: Taxonomy instance for transaction categorization
        """
        self._sync_tool = SyncTool(
            plaid_client=plaid_client,
            categorizer_factory=categorizer_factory,
            db=db,
            taxonomy=taxonomy,
        )

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute sync and return summary dict.

        Returns:
            JSON-serializable dict with sync results including:
            - status: "success" or "error"
            - items_synced: Number of Plaid items synced
            - total_added: Total transactions added
            - total_modified: Total transactions modified
            - total_removed: Total transactions removed
        """
        try:
            summary = await self._sync_tool.sync()
            return {"status": "success", **summary.to_dict()}
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
