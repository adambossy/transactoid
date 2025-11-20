from __future__ import annotations

from services.plaid_client import PlaidClient
from models.transaction import Transaction
from tools.categorize.categorizer_tool import Categorizer, CategorizedTransaction


class SyncTool:
    """
    Sync tool that calls Plaid's transaction sync API and categorizes all
    results using an LLM.
    """

    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        *,
        access_token: str,
        cursor: str | None = None,
    ) -> None:
        """
        Initialize the sync tool.

        Args:
            plaid_client: Plaid client instance
            categorizer: Categorizer instance for LLM-based categorization
            access_token: Plaid access token for the item
            cursor: Optional cursor for incremental sync (None for initial sync)
        """
        self._plaid_client = plaid_client
        self._categorizer = categorizer
        self._access_token = access_token
        self._cursor = cursor

    def sync(
        self,
        *,
        count: int = 500,
    ) -> tuple[list[CategorizedTransaction], str]:
        """
        Sync transactions from Plaid and categorize them.

        Args:
            count: Maximum number of transactions to fetch per request

        Returns:
            Tuple of (categorized_transactions, next_cursor)
        """
        # Call Plaid's sync_transactions API
        sync_result = self._plaid_client.sync_transactions(
            self._access_token,
            cursor=self._cursor,
            count=count,
        )

        # Extract transactions from sync result
        added: list[Transaction] = sync_result.get("added", [])
        modified: list[Transaction] = sync_result.get("modified", [])
        next_cursor = sync_result.get("next_cursor", "")

        # Combine added and modified transactions
        all_txns = added + modified

        # Categorize all transactions using LLM
        categorized_txns = self._categorizer.categorize(all_txns)

        return categorized_txns, next_cursor

