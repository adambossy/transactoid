from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.transaction import Transaction
from services.db import DB
from services.plaid_client import PlaidClient, PlaidClientError
from services.taxonomy import Taxonomy
from tools.categorize.categorizer_tool import CategorizedTransaction, Categorizer


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

    def sync(
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
                sync_result = self._plaid_client.sync_transactions(
                    self._access_token,
                    cursor=current_cursor,
                    count=count,
                )

                # Extract data from sync result
                added: list[Transaction] = sync_result.get("added", [])
                modified: list[Transaction] = sync_result.get("modified", [])
                removed: list[dict[str, Any]] = sync_result.get("removed", [])
                next_cursor = sync_result.get("next_cursor", "")
                has_more = sync_result.get("has_more", False)

                # Extract removed transaction IDs
                removed_transaction_ids = [
                    item.get("transaction_id", "")
                    for item in removed
                    if item.get("transaction_id")
                ]

                # Categorize added transactions
                categorized_added = self._categorizer.categorize(added)

                # Categorize modified transactions
                categorized_modified = self._categorizer.categorize(modified)

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
