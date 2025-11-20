from __future__ import annotations

from datetime import date

from services.plaid_client import PlaidClient, PlaidTransaction
from tools.categorize.categorizer_tool import Categorizer, CategorizedTransaction
from tools.ingest.ingest_tool import NormalizedTransaction


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
        added = sync_result.get("added", [])
        modified = sync_result.get("modified", [])
        next_cursor = sync_result.get("next_cursor", "")

        # Combine added and modified transactions
        all_plaid_txns = added + modified

        # Convert Plaid transactions to NormalizedTransaction
        normalized_txns = [
            self._plaid_to_normalized(txn) for txn in all_plaid_txns
        ]

        # Categorize all transactions using LLM
        categorized_txns = self._categorizer.categorize(normalized_txns)

        return categorized_txns, next_cursor

    def _plaid_to_normalized(
        self, plaid_txn: PlaidTransaction
    ) -> NormalizedTransaction:
        """
        Convert a Plaid transaction to a NormalizedTransaction.

        Args:
            plaid_txn: Plaid transaction dictionary

        Returns:
            NormalizedTransaction instance
        """
        # Parse date from string (Plaid returns YYYY-MM-DD)
        posted_at = date.fromisoformat(plaid_txn["date"])

        # Convert amount to cents (Plaid returns float dollars)
        amount_cents = int(plaid_txn["amount"] * 100)

        # Get currency (default to USD if not provided)
        currency = (
            plaid_txn.get("iso_currency_code")
            or plaid_txn.get("unofficial_currency_code")
            or "USD"
        ).upper()

        # Use merchant_name if available, otherwise use name
        merchant_descriptor = plaid_txn.get("merchant_name") or plaid_txn["name"]

        # Get institution name from item
        institution = (
            self._plaid_client.institution_name_for_item(self._access_token) or ""
        )

        return NormalizedTransaction(
            external_id=plaid_txn.get("transaction_id"),
            account_id=plaid_txn["account_id"],
            posted_at=posted_at,
            amount_cents=amount_cents,
            currency=currency,
            merchant_descriptor=merchant_descriptor,
            source="PLAID",
            source_file=None,
            institution=institution,
        )

