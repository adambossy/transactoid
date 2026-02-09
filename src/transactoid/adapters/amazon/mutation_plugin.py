"""Amazon mutation plugin for splitting orders into item-level transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from transactoid.adapters.amazon.logger import AmazonMatcherLogger
from transactoid.adapters.amazon.order_index import AmazonOrderIndex
from transactoid.adapters.amazon.plaid_matcher import (
    is_amazon_transaction,
    match_orders_to_transactions,
)
from transactoid.adapters.amazon.splitter import split_order_to_derived
from transactoid.tools.sync.mutation_plugin import MutationResult

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB
    from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction


@dataclass
class AmazonMutationPluginConfig:
    """Configuration for Amazon mutation plugin.

    Attributes:
        max_date_lag: Maximum days between order_date and posted_at (default: 30).
    """

    max_date_lag: int = 30


class AmazonMutationPlugin:
    """Mutation plugin that splits Amazon transactions by order items.

    Matches Plaid transactions to Amazon orders and splits them into
    item-level derived transactions with proportionally allocated
    tax and shipping.

    Attributes:
        name: Plugin identifier ("amazon_order_split").
        priority: Plugin priority (10, runs before default).
    """

    name: str = "amazon_order_split"
    priority: int = 10

    def __init__(self, db: DB, config: AmazonMutationPluginConfig) -> None:
        """Initialize plugin with configuration.

        Args:
            db: Database facade for loading scraped Amazon data.
            config: Plugin configuration.
        """
        self._db = db
        self._config = config
        self._index: AmazonOrderIndex | None = None
        self._plaid_id_to_order_id: dict[int, str] = {}
        self._logger = AmazonMatcherLogger()

    def initialize(self, plaid_txns: list[PlaidTransaction]) -> None:
        """Pre-compute matches for all Amazon transactions.

        Called once per batch for O(N+M) efficiency instead of O(N*M).

        Args:
            plaid_txns: All Plaid transactions in the current batch.
        """
        # Load Amazon order index from DB tables populated by browser scraping.
        self._index = AmazonOrderIndex.from_db(self._db)
        if self._index.order_count == 0:
            self._plaid_id_to_order_id = {}
            return
        self._logger.index_loaded(self._index.order_count, self._index.item_count)

        # Filter to Amazon transactions only
        amazon_txns = [
            t for t in plaid_txns if is_amazon_transaction(t.merchant_descriptor)
        ]

        if not amazon_txns:
            self._plaid_id_to_order_id = {}
            return

        self._logger.matching_start(len(amazon_txns), len(plaid_txns))

        # Match orders to transactions
        orders = list(self._index._orders.values())
        matches = match_orders_to_transactions(
            orders, amazon_txns, max_date_lag=self._config.max_date_lag
        )

        # Build reverse lookup: plaid_id -> order_id
        self._plaid_id_to_order_id = {}
        for order_id, plaid_id in matches.items():
            if plaid_id is not None:
                self._plaid_id_to_order_id[plaid_id] = order_id

    def should_handle(self, plaid_txn: PlaidTransaction) -> bool:
        """Return True if this is a matched Amazon transaction.

        Args:
            plaid_txn: The Plaid transaction to check.

        Returns:
            True if transaction was matched to an Amazon order.
        """
        return plaid_txn.plaid_transaction_id in self._plaid_id_to_order_id

    def process(
        self,
        plaid_txn: PlaidTransaction,
        old_derived: list[DerivedTransaction],
    ) -> MutationResult:
        """Split Amazon transaction into item-level derived transactions.

        Args:
            plaid_txn: The matched Amazon Plaid transaction.
            old_derived: Existing derived transactions for enrichment preservation.

        Returns:
            MutationResult with N derived transactions (one per item).
        """
        if self._index is None:
            return MutationResult(derived_data_list=[], handled=False)

        order_id = self._plaid_id_to_order_id.get(plaid_txn.plaid_transaction_id)
        if not order_id:
            return MutationResult(derived_data_list=[], handled=False)

        order = self._index.get_order(order_id)
        if not order:
            return MutationResult(derived_data_list=[], handled=False)

        items = self._index.get_items(order_id)

        # Log match found
        self._logger.match_found(
            plaid_txn.plaid_transaction_id,
            order_id,
            len(items),
            plaid_txn.amount_cents,
        )

        # Split order into item-level derived transactions
        derived_data_list = split_order_to_derived(plaid_txn, order, items)

        # Convert DerivedTransactionData to dict format
        result_list: list[dict[str, Any]] = []
        for dtd in derived_data_list:
            result_list.append(
                {
                    "plaid_transaction_id": dtd.plaid_transaction_id,
                    "external_id": dtd.external_id,
                    "amount_cents": dtd.amount_cents,
                    "posted_at": dtd.posted_at,
                    "merchant_descriptor": dtd.merchant_descriptor,
                    "category_id": None,
                    "is_verified": False,
                }
            )

        # Log split created
        self._logger.split_created(
            plaid_txn.plaid_transaction_id,
            len(result_list),
            [d["external_id"] for d in result_list],
        )

        # Preserve enrichments if old_derived has matching count
        if old_derived and len(old_derived) == len(result_list):
            for new_data, old in zip(result_list, old_derived, strict=True):
                if old.is_verified and old.category_id is not None:
                    new_data["category_id"] = old.category_id
                new_data["is_verified"] = old.is_verified
                if old.merchant_id is not None:
                    new_data["merchant_id"] = old.merchant_id

        return MutationResult(
            derived_data_list=result_list,
            handled=True,
        )
