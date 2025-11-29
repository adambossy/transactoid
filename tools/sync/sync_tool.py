from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

from models.transaction import Transaction
from services.plaid_client import PlaidClient
from tools.categorize.categorizer_tool import Categorizer
from tools.persist.persist_tool import PersistTool, SaveOutcome


@dataclass
class SyncSummary:
    """Summary of sync operation results."""

    total_added: int
    total_modified: int
    total_removed: int
    total_categorized: int
    total_persisted: int
    final_cursor: str
    persist_outcomes: list[SaveOutcome]


class SyncTool:
    """
    Sync tool that calls Plaid's transaction sync API and categorizes all
    results using an LLM with parallel processing.
    """

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        persist_tool: PersistTool,
        *,
        access_token: str,
        cursor: str | None = None,
    ) -> None:
        """
        Initialize the sync tool.

        Args:
            plaid_client: Plaid client instance
            categorizer: Categorizer instance for LLM-based categorization
            persist_tool: PersistTool instance for saving transactions
            access_token: Plaid access token for the item
            cursor: Optional cursor for incremental sync (None for initial sync)
        """
        self._plaid_client = plaid_client
        self._categorizer = categorizer
        self._persist_tool = persist_tool
        self._access_token = access_token
        self._cursor = cursor

    async def sync(
        self,
        *,
        count: int = 500,
        batch_size: int = 25,
        max_parallel_categorize: int = 4,
    ) -> SyncSummary:
        """
        Sync all transactions from Plaid with parallel categorization and persistence.

        Fetches pages sequentially from Plaid API, stores raw transactions immediately,
        batches them for categorization, and processes categorization in parallel.

        Args:
            count: Maximum number of transactions to fetch per Plaid API request
            batch_size: Number of transactions per categorize batch (default 25)
            max_parallel_categorize: Maximum concurrent categorize calls (default 4)

        Returns:
            SyncSummary with counts and final cursor
        """
        # Queue for categorization pipeline
        categorize_queue: asyncio.Queue[tuple[list[Transaction], str]] = asyncio.Queue()

        # Tracking variables
        sync_done = asyncio.Event()

        # Accumulators
        total_added = 0
        total_modified = 0
        total_removed = 0
        total_categorized = 0
        total_persisted = 0
        final_cursor = self._cursor or ""

        # Track processed cursors (for cursor advancement)
        processed_cursors: set[str] = set()
        cursor_to_batches: dict[str, list[list[Transaction]]] = {}
        cursor_lock = asyncio.Lock()

        # Shared list for persist outcomes
        persist_outcomes: list[SaveOutcome] = []
        outcomes_lock = asyncio.Lock()

        # Batch accumulator for categorize queue
        current_batch: list[Transaction] = []
        current_page_cursor: str | None = None

        async def sync_producer() -> None:
            """Producer: Fetch pages from Plaid API sequentially."""
            nonlocal current_batch, total_added, total_modified, total_removed
            nonlocal final_cursor, current_page_cursor

            cursor = self._cursor

            try:
                while True:
                    # Fetch page from Plaid (sequential)
                    # Use direct await if async, otherwise use to_thread
                    sync_method = self._plaid_client.sync_transactions
                    if inspect.iscoroutinefunction(sync_method):
                        sync_result = await sync_method(
                            self._access_token,
                            cursor=cursor,
                            count=count,
                        )
                    else:
                        sync_result = await asyncio.to_thread(
                            sync_method,
                            self._access_token,
                            cursor=cursor,
                            count=count,
                        )

                    # Store the cursor used for this sync call
                    page_cursor = cursor
                    next_cursor = sync_result.get("next_cursor", "")
                    has_more = sync_result.get("has_more", False)

                    # Extract transactions
                    added: list[Transaction] = sync_result.get("added", [])
                    modified: list[Transaction] = sync_result.get("modified", [])
                    removed: list[dict[str, Any]] = sync_result.get("removed", [])

                    all_to_categorize = added + modified

                    # CRITICAL: Store raw transactions immediately before categorization
                    # This ensures we don't lose them if categorization fails
                    if all_to_categorize:
                        save_raw_method = self._persist_tool.save_raw_transactions
                        if inspect.iscoroutinefunction(save_raw_method):
                            await save_raw_method(
                                all_to_categorize,
                                cursor=page_cursor,
                            )
                        else:
                            await asyncio.to_thread(
                                save_raw_method,
                                all_to_categorize,
                                cursor=page_cursor,
                            )

                        # Track this cursor and its batches
                        async with cursor_lock:
                            if page_cursor not in cursor_to_batches:
                                cursor_to_batches[page_cursor] = []
                            cursor_to_batches[page_cursor].append(all_to_categorize)

                    total_added += len(added)
                    total_modified += len(modified)
                    total_removed += len(removed)

                    # Add to current batch for categorization
                    current_batch.extend(all_to_categorize)
                    current_page_cursor = page_cursor

                    # When batch reaches size, send to categorize queue WITH cursor
                    while len(current_batch) >= batch_size:
                        batch = current_batch[:batch_size]
                        current_batch = current_batch[batch_size:]
                        await categorize_queue.put((batch, page_cursor))

                    # Update cursor for next iteration
                    cursor = next_cursor
                    final_cursor = cursor

                    # If no more pages, flush remaining batch and exit
                    if not has_more or not next_cursor:
                        if current_batch:
                            await categorize_queue.put((current_batch, page_cursor))
                            current_batch = []
                        break

            except Exception:
                # Error during sync - don't advance cursor
                # Re-raise to let caller handle
                raise
            finally:
                sync_done.set()

        async def categorize_and_persist_worker(worker_id: int) -> None:
            """Worker: Categorize batches and immediately persist them."""
            nonlocal total_categorized, total_persisted

            while True:
                try:
                    # Get batch from queue (with timeout to check if sync is done)
                    try:
                        batch, page_cursor = await asyncio.wait_for(
                            categorize_queue.get(),
                            timeout=1.0,
                        )
                    except TimeoutError:
                        # Check if sync is done and queue is empty
                        if sync_done.is_set() and categorize_queue.empty():
                            break
                        continue

                    # Categorize batch (this is the slow LLM call)
                    try:
                        categorize_method = self._categorizer.categorize
                        if inspect.iscoroutinefunction(categorize_method):
                            categorized = await categorize_method(batch)
                        else:
                            categorized = await asyncio.to_thread(
                                categorize_method,
                                batch,
                            )
                    except Exception:
                        # Categorization failed - batch is still in DB as raw
                        # Don't mark cursor as processed
                        categorize_queue.task_done()
                        continue

                    total_categorized += len(categorized)

                    # Immediately persist categorized transactions
                    try:
                        save_method = self._persist_tool.save_transactions
                        if inspect.iscoroutinefunction(save_method):
                            outcome = await save_method(categorized)
                        else:
                            outcome = await asyncio.to_thread(
                                save_method,
                                categorized,
                            )

                        total_persisted += len(categorized)

                        # Mark cursor as successfully processed
                        async with cursor_lock:
                            processed_cursors.add(page_cursor)

                        # Store outcome
                        async with outcomes_lock:
                            persist_outcomes.append(outcome)

                    except Exception:
                        # Persistence failed - but raw transactions are still in DB
                        # Can retry categorization later
                        categorize_queue.task_done()
                        continue

                    categorize_queue.task_done()

                except Exception:
                    # Log error but continue processing other batches
                    categorize_queue.task_done()
                    continue

        # Start all workers
        sync_task = asyncio.create_task(sync_producer())

        categorize_workers = [
            asyncio.create_task(categorize_and_persist_worker(i))
            for i in range(max_parallel_categorize)
        ]

        # Wait for sync to complete
        await sync_task

        # Wait for categorize queue to drain
        await categorize_queue.join()

        # Wait for categorize workers to finish
        await asyncio.gather(*categorize_workers, return_exceptions=True)

        # Only advance cursor if all batches for all cursors were processed
        # For now, we'll use the final_cursor from the last successful sync
        # In a more sophisticated implementation, we'd track which cursors
        # were fully processed and only advance to the last fully processed cursor

        return SyncSummary(
            total_added=total_added,
            total_modified=total_modified,
            total_removed=total_removed,
            total_categorized=total_categorized,
            total_persisted=total_persisted,
            final_cursor=final_cursor,
            persist_outcomes=persist_outcomes,
        )
