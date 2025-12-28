from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from models.transaction import Transaction
from services.db import DB
from services.plaid_client import PlaidClient, PlaidClientError
from services.taxonomy import Taxonomy
from tools.base import StandardTool
from tools.categorize.categorizer_tool import CategorizedTransaction, Categorizer
from tools.protocol import ToolInputSchema


@dataclass
class SyncResult:
    """Result from a single sync page."""

    categorized_added: list[CategorizedTransaction]
    categorized_modified: list[CategorizedTransaction]
    removed_transaction_ids: list[str]  # Plaid transaction IDs to delete
    next_cursor: str
    has_more: bool


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

    async def sync(
        self,
        *,
        count: int = 25,
    ) -> list[SyncResult]:
        """
        Sync all available transactions with automatic pagination.

        Handles pagination automatically, categorizes each page as it's fetched.

        Args:
            count: Maximum number of transactions per page (default: 25, max: 500)

        Returns:
            List of SyncResult objects, one per page processed

        Raises:
            PlaidClientError: If TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION occurs
                and cannot be recovered after retries
        """
        current_cursor = self._cursor
        pagination_start_cursor = current_cursor
        results: list[SyncResult] = []
        max_retries = 3
        retry_count = 0

        while True:
            try:
                # Call Plaid's sync_transactions API
                cursor_label = current_cursor or "initial"
                print(f"Fetching transactions from Plaid (cursor: {cursor_label})...")
                sync_result = self._plaid_client.sync_transactions(
                    self._access_token,
                    cursor=current_cursor,
                    count=count,
                )

                # Extract data from sync result
                added: list[Transaction] = sync_result.get("added", [])
                modified: list[Transaction] = sync_result.get("modified", [])
                removed: list[dict[str, Any]] = sync_result.get("removed", [])
                print(
                    f"Plaid fetch complete: {len(added)} added, "
                    f"{len(modified)} modified, {len(removed)} removed"
                )
                next_cursor = sync_result.get("next_cursor", "")
                has_more = sync_result.get("has_more", False)

                # Extract removed transaction IDs
                removed_transaction_ids = [
                    item.get("transaction_id", "")
                    for item in removed
                    if item.get("transaction_id")
                ]

                # Categorize added and modified transactions concurrently
                categorized_added, categorized_modified = await asyncio.gather(
                    self._categorizer.categorize(added),
                    self._categorizer.categorize(modified),
                )

                # Create SyncResult for this page
                page_result = SyncResult(
                    categorized_added=categorized_added,
                    categorized_modified=categorized_modified,
                    removed_transaction_ids=removed_transaction_ids,
                    next_cursor=next_cursor,
                    has_more=has_more,
                )

                # Persist transactions to database
                self._db.save_transactions(
                    self._taxonomy, categorized_added + categorized_modified
                )
                if removed_transaction_ids:
                    self._db.delete_transactions_by_external_ids(
                        removed_transaction_ids, source="PLAID"
                    )

                results.append(page_result)

                # If no more pages, break
                if not has_more:
                    break

                # Update cursor for next iteration
                current_cursor = next_cursor
                retry_count = 0  # Reset retry count on successful page

            except PlaidClientError as e:
                # Check if this is a mutation during pagination error
                error_msg = str(e)
                if "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in error_msg:
                    if retry_count < max_retries:
                        # Restart pagination from the beginning
                        current_cursor = pagination_start_cursor
                        results = []  # Clear partial results
                        retry_count += 1
                        continue
                    else:
                        # Max retries exceeded
                        raise PlaidClientError(
                            f"Failed to sync after {max_retries} retries due to "
                            "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
                        ) from e
                else:
                    # Re-raise other PlaidClientErrors
                    raise

        return results


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
            results = asyncio.run(self._sync_tool.sync())

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
