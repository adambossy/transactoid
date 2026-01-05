"""Amazon adapters for CSV loading and Plaid transaction matching."""

from transactoid.adapters.amazon.csv_loader import (
    AmazonItem,
    AmazonItemsCSVLoader,
    AmazonOrder,
    AmazonOrdersCSVLoader,
)
from transactoid.adapters.amazon.logger import AmazonMatcherLogger
from transactoid.adapters.amazon.mutation_plugin import (
    AmazonMutationPlugin,
    AmazonMutationPluginConfig,
)
from transactoid.adapters.amazon.order_index import AmazonOrderIndex
from transactoid.adapters.amazon.plaid_matcher import (
    is_amazon_transaction,
    match_orders_to_transactions,
)
from transactoid.adapters.amazon.splitter import (
    DerivedTransactionData,
    split_order_to_derived,
)

__all__ = [
    # CSV loading
    "AmazonItemsCSVLoader",
    "AmazonOrdersCSVLoader",
    "AmazonItem",
    "AmazonOrder",
    # Order index
    "AmazonOrderIndex",
    # Matching
    "is_amazon_transaction",
    "match_orders_to_transactions",
    # Splitting
    "DerivedTransactionData",
    "split_order_to_derived",
    # Mutation plugin
    "AmazonMutationPlugin",
    "AmazonMutationPluginConfig",
    # Logging
    "AmazonMatcherLogger",
]
